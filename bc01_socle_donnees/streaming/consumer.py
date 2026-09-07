"""
BC01 — Consumer Kafka : ingestion du flux de transactions vers le socle.

Pipeline par micro-lot (taille ou intervalle, ce qui arrive en premier) :
  1. valider le schéma JSON de chaque message — un message invalide part
     en DLQ (topic `transactions.dlq`) au lieu de bloquer le flux ;
  2. écarter les doublons déjà vus via un jeu Redis à expiration (défense
     en profondeur, en plus de la contrainte UNIQUE côté Postgres) ;
  3. écrire le lot valide dans staging.raw_transactions (ON CONFLICT DO
     NOTHING) puis appeler dwh.charger_faits_transactions('stream') —
     la MÊME fonction que le chargement batch ;
  4. ne committer les offsets Kafka QU'APRÈS l'écriture réussie en base
     (at-least-once : un crash avant l'étape 3 rejoue le lot, sans
     doublon grâce à l'idempotence des étapes 2/3) ;
  5. mettre à jour le feature store en ligne Redis (nb_tx_1h,
     montant_cumul_1h) — consommé par l'API de scoring temps réel (BC05).

Usage :
    python streaming/consumer.py
"""
import json
import logging
import os
import time

import psycopg2
import psycopg2.extras
import redis
from confluent_kafka import Consumer, Producer
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("consumer")

BATCH_SIZE = 200
FLUSH_INTERVAL_S = 2.0
DEDUP_TTL_S = 24 * 3600

REQUIRED_FIELDS = {
    "transaction_bk": str, "client_id": str, "horodatage": str,
    "montant": (int, float), "canal": str, "mcc_code": str,
    "pays_transaction": str, "distance_domicile_km": (int, float),
    "authentification": str,
}

INSERT_SQL = """
    INSERT INTO staging.raw_transactions
        (transaction_bk, client_id, horodatage, montant, canal, mcc_code,
         pays_transaction, distance_domicile_km, authentification, mode_ingestion)
    VALUES %s
    ON CONFLICT (transaction_bk) DO NOTHING;
"""


def get_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"),
        user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def get_redis_client():
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6380")),
        decode_responses=True,
    )


def validate_event(raw_value: bytes) -> tuple[dict | None, str | None]:
    try:
        event = json.loads(raw_value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"json_invalide: {exc}"

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in event:
            return None, f"champ_manquant: {field}"
        if not isinstance(event[field], expected_type):
            return None, f"type_invalide: {field}"

    return event, None


def is_duplicate(r: redis.Redis, transaction_bk: str) -> bool:
    """Lecture seule : ne marque rien. Le marquage n'a lieu qu'après écriture
    réussie en base (voir mark_seen), pour ne jamais perdre un message à
    cause d'un échec transitoire du lot Postgres."""
    return r.exists(f"dedup:{transaction_bk}") == 1


def mark_seen(r: redis.Redis, events: list[dict]):
    pipe = r.pipeline()
    for e in events:
        pipe.set(f"dedup:{e['transaction_bk']}", 1, ex=DEDUP_TTL_S)
    pipe.execute()


def update_online_features(r: redis.Redis, event: dict):
    client_id = event["client_id"]
    count_key = f"feat:{client_id}:nb_tx_1h"
    amount_key = f"feat:{client_id}:montant_cumul_1h"
    pipe = r.pipeline()
    pipe.incr(count_key)
    pipe.expire(count_key, 3600)
    pipe.incrbyfloat(amount_key, event["montant"])
    pipe.expire(amount_key, 3600)
    pipe.execute()


def send_to_dlq(dlq_producer: Producer, topic: str, raw_value: bytes, reason: str):
    envelope = json.dumps({"raw": raw_value.decode(errors="replace"), "erreur": reason})
    dlq_producer.produce(topic, value=envelope)


def flush_batch(pg_conn, events: list[dict]) -> int:
    """Écrit le lot en staging puis déclenche la transformation partagée. Renvoie le nb de faits insérés."""
    rows = [
        (e["transaction_bk"], e["client_id"], e["horodatage"], e["montant"], e["canal"],
         e["mcc_code"], e["pays_transaction"], e["distance_domicile_km"], e["authentification"], "stream")
        for e in events
    ]
    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, INSERT_SQL, rows)
        cur.execute("SELECT dwh.charger_faits_transactions('stream');")
        n_inserted = cur.fetchone()[0]
    pg_conn.commit()
    return n_inserted


def log_chargement(pg_conn, nb_lignes: int, duree_ms: int, statut: str, message: str = None):
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.log_chargement (source, mode, nb_lignes, duree_ms, statut, message, termine_at) "
            "VALUES ('consumer.py', 'stream', %s, %s, %s, %s, now());",
            (nb_lignes, duree_ms, statut, message),
        )
    pg_conn.commit()


def main():
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    topic = os.getenv("KAFKA_TOPIC", "transactions.raw")
    dlq_topic = f"{topic.rsplit('.', 1)[0]}.dlq" if "." in topic else f"{topic}.dlq"

    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": "fraud-ingestion",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,  # on committe nous-mêmes, après écriture réussie en base
    })
    consumer.subscribe([topic])
    dlq_producer = Producer({"bootstrap.servers": bootstrap})
    log.info("Consumer abonné à '%s' sur %s (DLQ : '%s')", topic, bootstrap, dlq_topic)

    pg_conn = get_pg_connection()
    r = get_redis_client()

    buffer_events: list[dict] = []
    last_msg = None
    last_flush = time.perf_counter()
    total_processed, total_rejected, total_duplicates = 0, 0, 0

    def do_flush():
        nonlocal buffer_events, last_msg, last_flush, total_processed
        if not buffer_events:
            last_flush = time.perf_counter()
            return
        t0 = time.perf_counter()
        try:
            n_inserted = flush_batch(pg_conn, buffer_events)
            duree_ms = int((time.perf_counter() - t0) * 1000)
            log_chargement(pg_conn, len(buffer_events), duree_ms, "OK")
            # Redis (dédup + features) n'est mis à jour qu'APRÈS le succès Postgres :
            # un échec de lot laisse Redis intact et le lot est rejoué tel quel.
            mark_seen(r, buffer_events)
            for e in buffer_events:
                update_online_features(r, e)
            consumer.commit(message=last_msg, asynchronous=False)
            total_processed += len(buffer_events)
            log.info(
                "Lot ingéré : %d messages -> %d faits nouveaux (%d ms) | total : %d",
                len(buffer_events), n_inserted, duree_ms, total_processed,
            )
        except Exception as exc:
            pg_conn.rollback()
            log.error("Échec du lot (offsets NON committés, sera rejoué) : %s", exc)
        finally:
            buffer_events = []
            last_flush = time.perf_counter()

    try:
        while True:
            msg = consumer.poll(timeout=0.5)

            if msg is not None and not msg.error():
                event, error = validate_event(msg.value())
                if error:
                    send_to_dlq(dlq_producer, dlq_topic, msg.value(), error)
                    dlq_producer.poll(0)
                    total_rejected += 1
                    last_msg = msg
                elif is_duplicate(r, event["transaction_bk"]):
                    total_duplicates += 1  # déjà vu récemment — on avance l'offset sans réécrire
                    last_msg = msg
                else:
                    buffer_events.append(event)
                    last_msg = msg
            elif msg is not None and msg.error():
                log.error("Erreur Kafka : %s", msg.error())

            if len(buffer_events) >= BATCH_SIZE or (time.perf_counter() - last_flush) >= FLUSH_INTERVAL_S:
                do_flush()

    except KeyboardInterrupt:
        log.info("Arrêt demandé par l'utilisateur")
    finally:
        do_flush()
        dlq_producer.flush()
        consumer.close()
        pg_conn.close()
        log.info(
            "Terminé — %d ingérées | %d rejetées (DLQ) | %d doublons filtrés",
            total_processed, total_rejected, total_duplicates,
        )


if __name__ == "__main__":
    main()
