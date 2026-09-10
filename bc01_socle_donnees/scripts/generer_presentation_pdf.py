"""Génère la présentation PDF du BC01 (architecture + enchaînement + rôles)."""
from pathlib import Path

from fpdf import FPDF

DOCS = Path(__file__).resolve().parents[1] / "docs"
OUT = DOCS / "BC01-presentation.pdf"
IMG = DOCS / "bc01-architecture.png"
FONT = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_B = Path(r"C:\Windows\Fonts\arialbd.ttf")


class Pdf(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("A", "", 9)
        self.set_text_color(90, 100, 115)
        self.cell(0, 8, "BC01 — Socle de données  |  Présentation", align="L")
        self.ln(3)
        self.set_draw_color(26, 82, 112)
        self.line(14, 15, 196, 15)
        self.ln(8)

    def footer(self):
        self.set_y(-14)
        self.set_font("A", "", 8)
        self.set_text_color(120, 128, 140)
        self.cell(0, 8, f"Détection de fraude — portfolio RNCP  ·  page {self.page_no()}/{{nb}}", align="C")

    def h1(self, t):
        self.set_font("AB", "", 15)
        self.set_text_color(18, 33, 46)
        self.multi_cell(0, 8, t)
        self.set_draw_color(26, 82, 112)
        self.set_line_width(0.6)
        y = self.get_y()
        self.line(14, y, 196, y)
        self.ln(4)

    def h2(self, t):
        self.ln(1)
        self.set_font("AB", "", 11.5)
        self.set_text_color(26, 82, 112)
        self.multi_cell(0, 6.5, t)
        self.ln(1.5)

    def p(self, t):
        self.set_font("A", "", 10.2)
        self.set_text_color(28, 34, 48)
        self.multi_cell(0, 5.6, t)
        self.ln(1.5)

    def bullet(self, t):
        self.set_font("A", "", 10.2)
        self.set_text_color(28, 34, 48)
        self.cell(5, 5.6, "-")
        self.multi_cell(0, 5.6, t)
        self.ln(0.8)

    def box(self, title, body, kind="info"):
        palette = {
            "info": ((238, 244, 246), (26, 82, 112)),
            "warn": ((248, 241, 230), (168, 99, 31)),
            "good": ((233, 243, 238), (47, 107, 79)),
        }
        bg, bd = palette[kind]
        x, start = 14, self.get_y()
        self.set_xy(x + 4, start + 2.5)
        self.set_font("AB", "", 9.8)
        self.set_text_color(*bd)
        self.multi_cell(174, 5.2, title)
        self.set_font("A", "", 9.5)
        self.set_text_color(42, 52, 68)
        self.set_x(x + 4)
        self.multi_cell(174, 5.1, body)
        end = self.get_y() + 2.5
        self.set_fill_color(*bg)
        self.rect(x, start, 182, end - start, "F")
        self.set_fill_color(*bd)
        self.rect(x, start, 2, end - start, "F")
        self.set_xy(x + 4, start + 2.5)
        self.set_font("AB", "", 9.8)
        self.set_text_color(*bd)
        self.multi_cell(174, 5.2, title)
        self.set_font("A", "", 9.5)
        self.set_text_color(42, 52, 68)
        self.set_x(x + 4)
        self.multi_cell(174, 5.1, body)
        self.set_y(end + 3)

    def table(self, headers, rows, widths):
        self.set_x(14)
        self.set_font("AB", "", 8.2)
        self.set_fill_color(26, 82, 112)
        self.set_text_color(255, 255, 255)
        for h, w in zip(headers, widths):
            self.cell(w, 6.5, h, 1, fill=True, align="C")
        self.ln()
        self.set_x(14)
        self.set_font("A", "", 8.2)
        self.set_text_color(28, 34, 48)
        fill = False
        for row in rows:
            if self.get_y() > 270:
                self.add_page()
                self.set_x(14)
            if fill:
                self.set_fill_color(244, 246, 249)
            else:
                self.set_fill_color(255, 255, 255)
            lh = 4.8
            n = 1
            for cell, w in zip(row, widths):
                n = max(n, int(self.get_string_width(str(cell)) / max(w - 2, 1)) + 1)
            rh = lh * n + 1.5
            y0, x0 = self.get_y(), 14
            for cell, w in zip(row, widths):
                self.set_xy(x0, y0)
                self.multi_cell(w, lh, str(cell), 0, fill=fill)
                x0 += w
            x0 = 14
            for w in widths:
                self.rect(x0, y0, w, rh)
                x0 += w
            self.set_y(y0 + rh)
            self.set_x(14)
            fill = not fill
        self.ln(2)


def build():
    pdf = Pdf(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, 16)
    pdf.add_font("A", "", str(FONT))
    pdf.add_font("AB", "", str(FONT_B))
    pdf.set_margins(14, 16, 14)

    # ===== COUVERTURE =====
    pdf.add_page()
    pdf.ln(28)
    pdf.set_x(14)
    pdf.set_font("A", "", 10)
    pdf.set_text_color(26, 82, 112)
    pdf.multi_cell(0, 7, "DETECTION DE FRAUDE BANCAIRE - PORTFOLIO RNCP")
    pdf.ln(8)
    pdf.set_x(14)
    pdf.set_font("AB", "", 22)
    pdf.set_text_color(18, 33, 46)
    pdf.multi_cell(0, 10, "BC01 — Présentation")
    pdf.set_x(14)
    pdf.set_font("A", "", 13)
    pdf.set_text_color(68, 80, 100)
    pdf.multi_cell(0, 7, "Socle de données : architecture, enchaînement et rôles")
    pdf.ln(8)
    pdf.set_draw_color(26, 82, 112)
    pdf.set_line_width(1.1)
    y_line = pdf.get_y()
    pdf.line(14, y_line, 85, y_line)
    pdf.set_y(y_line + 10)
    pdf.set_x(14)
    pdf.set_font("A", "", 10.5)
    pdf.set_text_color(42, 52, 68)
    pdf.multi_cell(
        0,
        6,
        "Ce document explique simplement le premier bloc du projet : comment les "
        "données sont générées, stockées (PostgreSQL en étoile), ingérées en batch "
        "et en streaming (Kafka), et contrôlées avant d'alimenter BC02 → BC06.",
    )
    pdf.ln(10)
    pdf.set_x(14)
    pdf.set_font("AB", "", 11)
    pdf.set_text_color(18, 33, 46)
    pdf.multi_cell(0, 7, "Sommaire")
    pdf.set_x(14)
    pdf.set_font("A", "", 10.5)
    for i, t in enumerate(
        [
            "Objectif du BC01",
            "Architecture globale (schéma)",
            "Les 4 couches PostgreSQL",
            "Enchaînement batch vs streaming",
            "Rôle de chaque script / fonction",
            "Garanties (idempotence, qualité)",
            "Comment démarrer / démontrer",
        ],
        1,
    ):
        pdf.set_x(14)
        pdf.set_text_color(26, 82, 112)
        pdf.cell(8, 6.5, f"{i}.")
        pdf.set_text_color(42, 52, 68)
        pdf.cell(160, 6.5, t)
        pdf.ln(6.5)

    # ===== 1 =====
    pdf.add_page()
    pdf.h1("1. Objectif du BC01")
    pdf.p(
        "Poser les fondations data du projet anti-fraude : un entrepôt PostgreSQL "
        "en schéma étoile, un feature store Redis pour le temps réel, et un pipeline "
        "Kafka. Les blocs suivants (analyse, ML, API) consomment ce socle."
    )
    pdf.box(
        "Choix clé : données synthétiques",
        "seed.py génère 5 000 clients et 400 000 transactions (taux fraude ~1,5 %). "
        "Contrairement aux CSV Kaggle (variables PCA anonymes), on contrôle le schéma "
        "métier, les typologies de fraude et la volumétrie.",
        "info",
    )
    pdf.p("Livrables principaux :")
    pdf.bullet("4 schémas SQL : staging / dwh / mart / ops")
    pdf.bullet("Une seule fonction de transformation batch + stream")
    pdf.bullet("10 contrôles qualité automatiques")
    pdf.bullet("Infra Docker : Postgres, Redis, Kafka, Adminer, Kafka UI")

    # ===== 2 =====
    pdf.h1("2. Architecture globale")
    pdf.p(
        "Deux voies d'ingestion (batch et stream) convergent vers la même porte "
        "SQL, puis vers le DWH et Redis."
    )
    if IMG.exists():
        # largeur utile ~182 mm
        pdf.image(str(IMG), x=14, w=182)
        pdf.ln(2)
        pdf.set_font("A", "", 8)
        pdf.set_text_color(100, 110, 120)
        pdf.cell(0, 5, "Figure 1 — Architecture BC01 (batch + streaming → DWH → mart / Redis)", align="C")
        pdf.ln(6)

    pdf.box(
        "Idée à retenir",
        "Batch (seed.py) et streaming (consumer.py) appellent la MÊME fonction "
        "dwh.charger_faits_transactions(mode). Les deux chemins ne peuvent pas diverger.",
        "good",
    )

    # ===== 3 =====
    pdf.add_page()
    pdf.h1("3. Les 4 couches PostgreSQL")
    pdf.table(
        ["Couche", "Rôle", "Exemples"],
        [
            ["staging", "Copie brute, aucune règle métier", "raw_transactions"],
            ["dwh", "Schéma en étoile (dimensions + faits)", "dim_*, fact_transactions"],
            ["mart", "Vues pour BC02→BC06", "v_kpis_globaux, v_profil_horaire"],
            ["ops", "Observabilité (hors chemin critique)", "log_chargement, controle_qualite"],
        ],
        [28, 78, 76],
    )
    pdf.h2("Schéma en étoile (dwh)")
    pdf.table(
        ["Table", "Rôle"],
        [
            ["dim_clients", "5 000 clients (UUID, segment, revenu) — pas de nom (RGPD)"],
            ["dim_agences", "10 agences du réseau"],
            ["dim_temps", "1 ligne / heure + membre Inconnu (clé 0)"],
            ["dim_canal", "Canal × MCC + membre Inconnu (clé 0)"],
            ["fact_transactions", "1 ligne = 1 transaction carte"],
            ["fact_card_blocks", "Historique des blocages carte"],
        ],
        [45, 137],
    )
    pdf.box(
        "Membre « Inconnu » (clé 0)",
        "Si une transaction stream a un horodatage hors fenêtre 2025, elle est quand "
        "même écrite avec temps_key=0. Pas de perte silencieuse. Le client reste en "
        "jointure stricte (client inconnu = anomalie).",
        "warn",
    )

    # ===== 4 =====
    pdf.h1("4. Enchaînement batch vs streaming")
    pdf.h2("4.1 Voie batch (historique labellisé)")
    pdf.bullet("1. docker compose up -d  (infra)")
    pdf.bullet("2. seed.py charge dimensions + staging (is_fraud déjà connu)")
    pdf.bullet("3. seed.py appelle charger_faits_transactions('batch')")
    pdf.bullet("4. quality_checks.py → 10/10")
    pdf.bullet("5. BC02→BC06 consomment fact_transactions (mode batch)")

    pdf.h2("4.2 Voie streaming (temps réel)")
    pdf.bullet("1. consumer.py écoute Kafka (micro-lots 200 msgs / 2 s)")
    pdf.bullet("2. producer.py publie ~N txs/s sur transactions.raw")
    pdf.bullet("3. Validation JSON → DLQ si invalide")
    pdf.bullet("4. Dédup Redis → insert staging → charger_faits('stream')")
    pdf.bullet("5. Mise à jour Redis (nb_tx_1h, montant_cumul_1h) → API BC05")
    pdf.bullet("6. Commit offset Kafka APRÈS succès Postgres (at-least-once)")

    # ===== 5 =====
    pdf.add_page()
    pdf.h1("5. Rôle de chaque script / fonction")

    pdf.h2("5.1 SQL (initialisation Docker)")
    pdf.table(
        ["Fichier", "Rôle"],
        [
            ["00_schemas.sql", "Crée staging, dwh, mart, ops"],
            ["01_dwh_star.sql", "Tables dimensions + faits"],
            ["02_staging.sql", "Table raw_transactions"],
            ["03_ops.sql", "log_chargement + controle_qualite"],
            ["04_transform.sql", "Fonction charger_faits_transactions"],
            ["05_mart.sql", "Vues KPIs / profil horaire / top fraude"],
        ],
        [45, 137],
    )

    pdf.h2("5.2 data/seed.py (batch)")
    pdf.table(
        ["Fonction", "Rôle"],
        [
            ["truncate_all", "Vide les tables pour un rechargement propre"],
            ["seed_unknown_members", "Insère les membres Inconnu (clé 0)"],
            ["seed_agences / seed_canal / seed_temps", "Remplit les dimensions de référence"],
            ["seed_clients", "Génère 5 000 clients (UUID, segment, revenu)"],
            ["seed_staging_transactions", "Génère les txs labellisées + 6 typologies fraude"],
            ["charger_faits", "Appelle la fonction SQL unique (mode batch)"],
            ["log_chargement_*", "Journalise début/fin dans ops.log_chargement"],
        ],
        [70, 112],
    )

    pdf.h2("5.3 streaming/producer.py")
    pdf.table(
        ["Fonction", "Rôle"],
        [
            ["fetch_client_ids", "Lit des client_id réels dans dim_clients"],
            ["make_event", "Construit un JSON transaction (clé métier unique)"],
            ["main", "Publie sur Kafka à un débit configurable"],
        ],
        [50, 132],
    )

    pdf.h2("5.4 streaming/consumer.py")
    pdf.table(
        ["Fonction", "Rôle"],
        [
            ["validate_event", "Vérifie le JSON (sinon → DLQ)"],
            ["is_duplicate / mark_seen", "Déduplication Redis (TTL 24h)"],
            ["flush_batch", "Insert staging + charger_faits('stream')"],
            ["update_online_features", "Met à jour nb_tx_1h / montant_cumul_1h"],
            ["send_to_dlq", "Isole les messages malformés"],
            ["log_chargement", "Trace chaque micro-lot dans ops"],
        ],
        [55, 127],
    )

    pdf.add_page()
    pdf.h2("5.5 Fonction SQL centrale")
    pdf.box(
        "dwh.charger_faits_transactions(p_mode)",
        "Lit staging (traite=FALSE, filtre batch/stream) → joint dim_clients (strict) "
        "+ dim_temps/canal (LEFT + Inconnu) → insert fact_transactions "
        "ON CONFLICT DO NOTHING → marque traite=TRUE. Idempotente.",
        "good",
    )

    pdf.h2("5.6 scripts/quality_checks.py")
    pdf.p("10 contrôles SQL journalisés dans ops.controle_qualite, par ex. :")
    pdf.bullet("FK complètes dans fact_transactions")
    pdf.bullet("Intégrité client_id staging ↔ dim_clients")
    pdf.bullet("Unicité transaction_bk")
    pdf.bullet("Cohérence montant / distance / label")
    pdf.bullet("Taux de fraude plausible (0,5 % – 3 %)")
    pdf.bullet("Fraîcheur staging (lignes non transformées)")

    # ===== 6 =====
    pdf.h1("6. Garanties")
    pdf.table(
        ["Propriété", "Mécanisme"],
        [
            ["Idempotence batch", "TRUNCATE + clés TX déterministes"],
            ["Idempotence stream", "ON CONFLICT DO NOTHING + dédup Redis"],
            ["At-least-once", "Commit Kafka après écriture Postgres"],
            ["Pas de doublon producteur", "enable.idempotence + acks=all"],
            ["Messages invalides", "Topic DLQ, flux non bloqué"],
        ],
        [50, 132],
    )

    # ===== 7 =====
    pdf.h1("7. Démarrer / démontrer")
    pdf.box(
        "Commandes",
        "docker compose up -d\n"
        "python bc01_socle_donnees/data/seed.py --clients 5000 --transactions 400000 --fraud-rate 0.015\n"
        "python bc01_socle_donnees/scripts/quality_checks.py\n"
        "# optionnel streaming :\n"
        "python bc01_socle_donnees/streaming/consumer.py\n"
        "python bc01_socle_donnees/streaming/producer.py --rate 5",
        "info",
    )
    pdf.p("Interfaces utiles : Adminer http://localhost:8080 · Kafka UI http://localhost:8090")
    pdf.ln(2)
    pdf.h2("Phrase soutenance (30 s)")
    pdf.p(
        "« Le BC01 pose un DWH PostgreSQL en étoile avec quatre couches. Batch et "
        "streaming passent par la même fonction SQL. Kafka + Redis alimentent le "
        "temps réel, dix contrôles qualité valident le socle avant les blocs ML. »"
    )

    DOCS.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"PDF écrit : {OUT}")


if __name__ == "__main__":
    build()
