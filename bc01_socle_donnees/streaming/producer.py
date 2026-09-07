"""
BC01 — Producer Kafka : simule l'arrivée en temps réel de transactions
carte bancaire.

Pique des client_id existants dans dim_clients (pour rester cohérent
avec le référentiel déjà chargé) et publie un événement JSON par
transaction sur le topic Kafka, à intervalle aléatoire (loi
exponentielle) pour imiter un flux réel.

Usage :
    python streaming/producer.py --rate 5      # ~5 transactions/seconde en moyenne
    python streaming/producer.py --count 1000  # s'arrête après 1000 messages
"""
import argparse
import json
import logging
import os
import time
import uuid
from datetime import datetime

import numpy as np
import psycopg2
from confluent_kafka import Producer
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("producer")

RNG = np.random.default_rng()

CANAUX = [
    ("en_ligne", "5411"), ("en_ligne", "5311"), ("en_ligne", "4829"),
    ("sans_contact", "5812"), ("sans_contact", "5912"),
    ("puce", "5541"), ("puce", "5411"), ("puce", "5921"),
    ("distributeur", "6011"),
]
PAYS = ["FR"] * 15 + ["ES", "DE", "IT", "GB", "BE", "RO", "NG"]  # FR très majoritaire
AUTHENTIFICATIONS = ["puce_pin", "3ds", "none"]
AUTH_WEIGHTS = [0.55, 0.35, 0.10]


def fetch_client_ids(limit: int = 5000) -> list[str]:
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"),
        user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )
    with conn.cursor() as cur:
        cur.execute("SELECT client_id FROM dwh.dim_clients ORDER BY random() LIMIT %s;", (limit,))
        ids = [str(r[0]) for r in cur.fetchall()]
    conn.close()
    if not ids:
        raise RuntimeError("dwh.dim_clients est vide — lance d'abord data/seed.py")
    return ids


def make_event(client_ids: list[str]) -> dict:
    """
    transaction_bk est généré ICI, une seule fois, et voyage avec le message.
    C'est ce qui rend une re-livraison Kafka (at-least-once) sans danger :
    le consumer verra toujours la même clé métier pour le même événement,
    donc `ON CONFLICT (transaction_bk) DO NOTHING` absorbe le doublon.
    """
    canal, mcc = CANAUX[RNG.integers(0, len(CANAUX))]
    return {
        "transaction_bk": f"TX-STREAM-{uuid.uuid4().hex}",
        "client_id": str(RNG.choice(client_ids)),
        "horodatage": datetime.now().isoformat(),
        "montant": round(float(RNG.lognormal(mean=np.log(45), sigma=0.9)), 2),
        "canal": canal,
        "mcc_code": mcc,
        "pays_transaction": str(RNG.choice(PAYS)),
        "distance_domicile_km": round(float(abs(RNG.normal(8, 15))), 2),
        "authentification": str(RNG.choice(AUTHENTIFICATIONS, p=AUTH_WEIGHTS)),
    }


def delivery_report(err, msg):
    if err is not None:
        log.error("Échec de livraison : %s", err)


def main():
    parser = argparse.ArgumentParser(description="Producer Kafka — flux de transactions simulé")
    parser.add_argument("--bootstrap", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094"))
    parser.add_argument("--topic", default=os.getenv("KAFKA_TOPIC", "transactions.raw"))
    parser.add_argument("--rate", type=float, default=5.0, help="transactions/seconde en moyenne")
    parser.add_argument("--count", type=int, default=0, help="0 = infini")
    args = parser.parse_args()

    client_ids = fetch_client_ids()
    log.info("%d client_id chargés depuis dim_clients", len(client_ids))

    # enable.idempotence : le broker déduplique lui-même les retries réseau
    # du producer (au niveau TCP/partition) — première ligne de défense,
    # complétée par la clé métier transaction_bk côté application.
    producer = Producer({
        "bootstrap.servers": args.bootstrap,
        "enable.idempotence": True,
        "acks": "all",
    })
    log.info("Producer connecté à %s — topic '%s' (idempotence activée)", args.bootstrap, args.topic)

    sent = 0
    try:
        while args.count == 0 or sent < args.count:
            event = make_event(client_ids)
            producer.produce(
                args.topic,
                key=event["client_id"],
                value=json.dumps(event),
                callback=delivery_report,
            )
            producer.poll(0)
            sent += 1
            if sent % 100 == 0:
                log.info("%d messages envoyés", sent)
            time.sleep(RNG.exponential(1.0 / args.rate))
    except KeyboardInterrupt:
        log.info("Arrêt demandé par l'utilisateur")
    finally:
        producer.flush()
        log.info("Terminé — %d messages envoyés au total", sent)


if __name__ == "__main__":
    main()
