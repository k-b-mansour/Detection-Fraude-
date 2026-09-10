"""Génère un rapport PDF synthétique du BC06 (version pédagogique)."""
from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parents[1] / "docs" / "BC06-rapport.pdf"
FONT = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_B = Path(r"C:\Windows\Fonts\arialbd.ttf")


class Rapport(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("ArialFR", "", 9)
        self.set_text_color(90, 100, 115)
        self.cell(0, 8, "BC06 — Gestion de projet, conformité RGPD & KPIs métier", align="L")
        self.ln(4)
        self.set_draw_color(26, 82, 112)
        self.set_line_width(0.4)
        self.line(15, 16, 195, 16)
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("ArialFR", "", 8)
        self.set_text_color(120, 128, 140)
        self.cell(0, 8, f"Détection de fraude — portfolio RNCP  |  page {self.page_no()}/{{nb}}", align="C")

    def h1(self, text):
        self.set_font("ArialFR-B", "", 16)
        self.set_text_color(18, 33, 46)
        self.multi_cell(0, 9, text)
        self.set_draw_color(26, 82, 112)
        self.set_line_width(0.7)
        y = self.get_y()
        self.line(15, y, 195, y)
        self.ln(5)

    def h2(self, text):
        self.ln(2)
        self.set_font("ArialFR-B", "", 12)
        self.set_text_color(26, 82, 112)
        self.multi_cell(0, 7, text)
        self.ln(2)

    def p(self, text):
        self.set_font("ArialFR", "", 10.5)
        self.set_text_color(28, 34, 48)
        self.multi_cell(0, 5.8, text)
        self.ln(2)

    def bullet(self, text):
        self.set_font("ArialFR", "", 10.5)
        self.set_text_color(28, 34, 48)
        self.cell(6, 5.8, "-")
        self.multi_cell(0, 5.8, text)
        self.ln(1)

    def callout(self, title, text, kind="info"):
        colors = {
            "info": ((238, 244, 246), (26, 82, 112)),
            "warn": ((248, 241, 230), (168, 99, 31)),
            "good": ((233, 243, 238), (47, 107, 79)),
        }
        bg, border = colors[kind]
        x = 15
        start = self.get_y()
        self.set_xy(x + 4, start + 2.5)
        self.set_font("ArialFR-B", "", 10)
        self.set_text_color(*border)
        self.multi_cell(172, 5.5, title)
        self.set_font("ArialFR", "", 9.8)
        self.set_text_color(42, 52, 68)
        self.set_x(x + 4)
        self.multi_cell(172, 5.3, text)
        end = self.get_y() + 2.5
        # fond
        self.set_fill_color(*bg)
        self.rect(x, start, 180, end - start, style="F")
        self.set_fill_color(*border)
        self.rect(x, start, 2, end - start, style="F")
        # réécrire le texte par-dessus le fond
        self.set_xy(x + 4, start + 2.5)
        self.set_font("ArialFR-B", "", 10)
        self.set_text_color(*border)
        self.multi_cell(172, 5.5, title)
        self.set_font("ArialFR", "", 9.8)
        self.set_text_color(42, 52, 68)
        self.set_x(x + 4)
        self.multi_cell(172, 5.3, text)
        self.set_y(end + 3)

    def table(self, headers, rows, col_widths=None):
        if col_widths is None:
            col_widths = [180 / len(headers)] * len(headers)
        self.set_font("ArialFR-B", "", 8.5)
        self.set_fill_color(26, 82, 112)
        self.set_text_color(255, 255, 255)
        for h, w in zip(headers, col_widths):
            self.cell(w, 7, h, border=1, fill=True, align="C")
        self.ln()
        self.set_font("ArialFR", "", 8.5)
        self.set_text_color(28, 34, 48)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(244, 246, 249)
            else:
                self.set_fill_color(255, 255, 255)
            # compute row height
            line_h = 5.2
            nlines = 1
            for cell, w in zip(row, col_widths):
                nlines = max(nlines, max(1, self.get_string_width(str(cell)) // (w - 2) + 1))
            row_h = line_h * nlines + 2
            if self.get_y() + row_h > 275:
                self.add_page()
                self.set_font("ArialFR-B", "", 8.5)
                self.set_fill_color(26, 82, 112)
                self.set_text_color(255, 255, 255)
                for h, w in zip(headers, col_widths):
                    self.cell(w, 7, h, border=1, fill=True, align="C")
                self.ln()
                self.set_font("ArialFR", "", 8.5)
                self.set_text_color(28, 34, 48)
            y0 = self.get_y()
            x0 = self.get_x()
            for cell, w in zip(row, col_widths):
                self.set_xy(x0, y0)
                self.multi_cell(w, line_h, str(cell), border=0, fill=fill)
                x0 += w
            # draw borders
            x0 = 15
            for w in col_widths:
                self.rect(x0, y0, w, row_h)
                x0 += w
            self.set_y(y0 + row_h)
            fill = not fill
        self.ln(3)


def build():
    pdf = Rapport(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("ArialFR", "", str(FONT))
    pdf.add_font("ArialFR-B", "", str(FONT_B))
    pdf.set_margins(15, 18, 15)

    # ---- COVER ----
    pdf.add_page()
    pdf.ln(35)
    pdf.set_font("ArialFR", "", 10)
    pdf.set_text_color(26, 82, 112)
    pdf.cell(0, 8, "DETECTION DE FRAUDE BANCAIRE  ·  PROJET PORTFOLIO RNCP")
    pdf.ln(14)
    pdf.set_font("ArialFR-B", "", 24)
    pdf.set_text_color(18, 33, 46)
    pdf.multi_cell(0, 11, "BC06 — Rapport de synthèse")
    pdf.ln(2)
    pdf.set_font("ArialFR", "", 14)
    pdf.set_text_color(68, 80, 100)
    pdf.multi_cell(0, 8, "Gestion de projet, conformité RGPD et KPIs métier")
    pdf.ln(10)
    pdf.set_draw_color(26, 82, 112)
    pdf.set_line_width(1.2)
    pdf.line(15, pdf.get_y(), 90, pdf.get_y())
    pdf.ln(10)
    pdf.set_font("ArialFR", "", 11)
    pdf.set_text_color(42, 52, 68)
    pdf.multi_cell(
        0,
        6.5,
        "Ce document explique le rôle du bloc 6, comment les deux scripts "
        "fonctionnent, et ce que signifient les résultats chiffrés "
        "(audit RGPD 6/8 et comparaison économique des seuils 0,50 vs 0,98).",
    )
    pdf.ln(12)
    pdf.set_font("ArialFR-B", "", 11)
    pdf.set_text_color(18, 33, 46)
    pdf.cell(0, 7, "Sommaire")
    pdf.ln(8)
    pdf.set_font("ArialFR", "", 10.5)
    for i, t in enumerate(
        [
            "Objectif du BC06",
            "Place dans le projet (BC01 → BC06)",
            "Audit RGPD exécutable",
            "KPIs métier et impact financier",
            "Lecture pour la soutenance",
            "Limites et suite",
        ],
        1,
    ):
        pdf.set_text_color(26, 82, 112)
        pdf.cell(8, 7, f"{i}.")
        pdf.set_text_color(42, 52, 68)
        pdf.cell(0, 7, t)
        pdf.ln(7)

    # ---- 1 ----
    pdf.add_page()
    pdf.h1("1. Objectif du BC06")
    pdf.p(
        "Le BC06 n'entraîne pas un nouveau modèle. Il clôt le projet sur deux "
        "questions que le métier et le jury posent toujours : le système est-il "
        "conforme (RGPD) ? et quel seuil de décision rapporte le plus (euros) ?"
    )
    pdf.p("Deux scripts exécutables répondent à ces questions :")
    pdf.bullet("audit_rgpd.py — 8 contrôles automatiques sur le schéma réel et les artefacts")
    pdf.bullet("kpis_metier.py — impact financier des seuils 0,50 et 0,98 du LightGBM (BC03)")
    pdf.callout(
        "Principe",
        "Comme au BC01 (quality_checks), un contrôle est une requête / une mesure, "
        "pas une affirmation. L'audit peut (et doit) trouver des non-conformités.",
        "info",
    )

    # ---- 2 ----
    pdf.h1("2. Place dans le projet")
    pdf.table(
        ["Bloc", "Rôle", "Livrable clé"],
        [
            ["BC01", "Socle données", "400k txs, DWH, Kafka, Redis"],
            ["BC02", "Comprendre", "Déséquilibre, profiling, anomalies"],
            ["BC03", "Modèle supervisé", "LightGBM AUC 0,998 + SHAP"],
            ["BC04", "Deep learning", "Autoencodeur + LSTM"],
            ["BC05", "Industrialisation", "API FastAPI, Docker, CI/CD, drift"],
            ["BC06", "Gouvernance", "RGPD + KPIs € + bilan"],
        ],
        [22, 42, 116],
    )
    pdf.p(
        "Sans le BC06, on aurait un bon modèle et une API, mais pas de preuve "
        "de conformité ni d'arbitrage économique du seuil — indispensables en contexte bancaire."
    )

    # ---- 3 ----
    pdf.h1("3. Audit RGPD exécutable")
    pdf.h2("3.1 Comment ça marche")
    pdf.p(
        "Le script interroge information_schema (schémas dwh/staging), vérifie "
        "la présence des artefacts SHAP/API, et journalise chaque contrôle dans "
        "ops.audit_conformite. Les résultats sont aussi exportés dans "
        "outputs/resume_audit_rgpd.json."
    )
    pdf.h2("3.2 Résultat : 6/8 conformes")
    pdf.table(
        ["Principe RGPD", "Contrôle", "Statut"],
        [
            ["Minimisation (Art. 5.1.c)", "Pas de nom/email/IBAN/carte personne physique", "OK"],
            ["Pseudonymisation (Art. 4.5)", "client_id = UUID opaque", "OK"],
            ["Sécurité (Art. 32)", "Pas de n° de carte / CVV stocké", "OK"],
            ["Explication (Art. 22)", "SHAP hors-ligne (BC03) + en ligne (BC05)", "OK"],
            ["Accountability (Art. 5.2)", "Journaux ops.log_chargement / controle_qualite", "OK"],
            ["Droits personnes (15-17)", "Pas de table identité ↔ pseudonyme", "OK"],
            ["Conservation (Art. 5.1.e)", "Politique de purge automatique", "KO"],
            ["Sécurité (Art. 32)", "Secrets non commités en clair", "KO"],
        ],
        [55, 100, 25],
    )
    pdf.callout(
        "Les deux KO sont assumés",
        "1) Aucune purge : les transactions restent indéfiniment (rétention type 5 ans "
        "anti-blanchiment à formaliser). 2) Mot de passe de démo fraud_secret dans "
        "docker-compose / .env.example — acceptable en local, à externaliser (vault / secrets CI) "
        "avant un vrai déploiement.",
        "warn",
    )
    pdf.callout(
        "Faux positif corrigé",
        "Le contrôle « nom » avait signalé dim_agences.nom (nom d'agence, pas de personne). "
        "Corrigé en excluant cette table avec justification dans le script — pas en masquant l'alerte.",
        "good",
    )

    # ---- 4 ----
    pdf.add_page()
    pdf.h1("4. KPIs métier — impact financier")
    pdf.h2("4.1 Méthode")
    pdf.p(
        "Sur les 80 000 transactions de test du BC03 (même split temporel), on recharge "
        "le LightGBM et on compare deux seuils. Hypothèse explicite : une fausse alerte "
        "coûte 8 € (vérification analyste). Le montant d'une fraude manquée est le montant "
        "réel de la transaction (donnée, pas une hypothèse)."
    )
    pdf.p("Bénéfice net ≈ fraude évitée − coût des fausses alertes.")
    pdf.h2("4.2 Résultats")
    pdf.table(
        ["Indicateur", "Seuil 0,50", "Seuil 0,98 (opti F1)"],
        [
            ["Fraude évitée", "292 884 €", "266 895 €"],
            ["Fraude manquée", "4 355 €", "30 344 €"],
            ["Fausses alertes", "758 × 8 € = 6 064 €", "122 × 8 € = 976 €"],
            ["Bénéfice net", "286 820 €", "265 919 €"],
        ],
        [55, 62.5, 62.5],
    )
    pdf.callout(
        "Constat central (+20 901 € en faveur du seuil 0,50)",
        "Le seuil qui maximise le F1 (0,98) n'est pas le plus rentable ici. "
        "Pourquoi ? Une fraude manquée coûte en moyenne beaucoup plus qu'une fausse alerte "
        "à 8 €. Le F1 traite ces deux erreurs comme équivalentes — une banque ne le fait pas.",
        "good",
    )
    pdf.p(
        "Conclusion opérationnelle : le « bon » seuil dépend du coût réel de la fausse alerte "
        "(à valider avec le métier). Si ce coût monte fortement, l'arbitrage peut revenir "
        "vers un seuil plus haut. L'API BC05 expose donc les deux lectures (0,50 et 0,98)."
    )

    # ---- 5 ----
    pdf.h1("5. Lecture pour la soutenance")
    pdf.bullet(
        "BC06 = gouvernance : conformité mesurée + valeur économique du modèle."
    )
    pdf.bullet(
        "Audit RGPD 6/8 avec KO documentés = maturité (un audit 8/8 sans manque serait suspect)."
    )
    pdf.bullet(
        "KPIs € : le F1 ne décide pas seul ; le seuil est un arbitrage métier."
    )
    pdf.bullet(
        "Phrase type : « Le seuil optimisé F1 laisse passer 30 k€ de fraude ; "
        "au seuil 0,50 le bénéfice net est supérieur de ~21 k€ sur la période de test. »"
    )

    # ---- 6 ----
    pdf.h1("6. Limites et suite")
    pdf.table(
        ["Limite", "Piste"],
        [
            ["Pas de purge / rétention", "Politique formalisée + job d'archivage"],
            ["Secrets de démo en clair", "Vault / secrets GitHub Actions"],
            ["Coût FA = hypothèse 8 €", "Calibrage avec équipes fraude réelles"],
            ["Données synthétiques", "Validation sur jeu externe (ex. Sparkov)"],
        ],
        [75, 105],
    )
    pdf.ln(2)
    pdf.h2("Conclusion")
    pdf.p(
        "Les six blocs forment une chaîne : données → analyse → modèle → deep learning → "
        "API → gouvernance. Le BC06 montre que la performance ML n'est pas la fin du projet : "
        "il faut aussi prouver la conformité et chiffrer l'impact métier. C'est ce qui transforme "
        "un notebook en démarche professionnelle défendable."
    )
    pdf.callout(
        "Scripts à relancer",
        "python bc06_gestion_projet/scripts/audit_rgpd.py\n"
        "python bc06_gestion_projet/scripts/kpis_metier.py",
        "info",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"PDF écrit : {OUT}")


if __name__ == "__main__":
    build()
