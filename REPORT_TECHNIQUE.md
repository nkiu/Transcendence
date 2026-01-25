TRANSCENDENCE – Rapport technique (fonctionnement du logiciel)
==============================================================

Objectif du document
--------------------
Ce rapport décrit comment fonctionne TRANSCENDENCE du point de vue logiciel : flux d’execution,
modules principaux, structure des donnees, interaction LLM, et cycle de simulation. L’objectif
est d’expliquer le systeme a un passionne de programmation (non‑pro) avec un niveau de detail
approfondi mais accessible.


1) Vue d’ensemble (ce que fait le logiciel)
-------------------------------------------
TRANSCENDENCE est une simulation de civilisation a base de cycles. Chaque cycle :
- applique des regles deterministes (regles de type "DND-like"),
- met a jour des statistiques (cohesion, stabilite, etc.),
- produit des evenements et des marques (marks),
- produit un texte narratif (optionnel) via un LLM local (Ollama),
- enregistre tout dans une base SQLite.

La simulation ne depend pas du LLM pour les decisions. Le LLM est un “temoin” qui ecrit ce que
les civilisations pensent vivre, mais les causes et effets sont fixes par les regles.

Le programme est une application desktop (Tkinter). On choisit une base de donnees, un ruleset
et un set de prompts, puis la simulation tourne en boucle jusqu’a extinction de toutes les
civilisations. Quand l’univers finit, une fenetre finale affiche des “obituaries”.


2) Architecture logique (modules clefs)
---------------------------------------
Les modules principaux sont :
- `lib/app.py` : demarrage, choix de base et parametres, creation de l’UI.
- `lib/ui.py` : interface graphique et loop de simulation (thread worker).
- `lib/sim.py` : orchestration du cycle (regles + LLM + persistence).
- `lib/rules_engine.py` : moteur de regles (eligibilite, evenements, application d’effets).
- `rulesets/*.py` : variantes de regles (harsh, star_trek_lite, cheat_utopia).
- `lib/db.py` : base SQLite (schema, acces et export snapshot).
- `lib/llm.py` : client LLM (Ollama), generation et parsing.
- `prompts/*.py` : prompts LLM (format de sortie strict).
- `lib/narrative_parser.py` : parse des sections LLM (LOG/GOD/etc).

La separation principale est :
UI -> Simulation -> Regles -> Persistance -> LLM (si active)


3) Demarrage et configuration (App UI)
--------------------------------------
Au lancement (`Transcendence.py` -> `lib/app.py`):
1. Une fenetre “Select Game” est ouverte.
2. L’utilisateur choisit : nouvelle base ou charge une base existante.
3. Il peut activer le LLM (Ollama), choisir un modele, et un ruleset.
4. Il peut modifier les prompts (events, civ, master) via des onglets.
5. Les choix sont sauvegardes dans la base via `run_settings`.

Ensuite :
- `Simulation(db)` est creee.
- `AppUI(root, sim)` est creee et lance la boucle.

Le fait d’avoir la configuration en base rend les runs reproductibles : prompt set,
ruleset, activation LLM, seed, etc.


4) Cycle de simulation (niveau macro)
-------------------------------------
Le “coeur” d’un cycle est dans `Simulation._run_single_cycle` :
1. Creation d’un nouveau cycle en base.
2. Chargement de l’etat (civilisations + universe state).
3. Application des regles via `RulesEngine.roll_cycle`.
4. Persist des resultats (stats, events, marks, delayed effects).
5. Generation LLM (civilisations + master) si LLM actif.
6. Sauvegarde de “cycle_records” (snapshot JSON detaille).
7. Mise a jour de “last_cycle” et check d’extinction globale.

Important : si l’univers est termine, la simulation ne fait plus de run LLM
et bascule sur la fin (UI + obituaries).


5) Modelisation des donnees (SQLite)
------------------------------------
La base SQLite est initialisee par `Database._init_schema`. Tables principales :

- `cycles` : chaque cycle, avec dates et resume.
- `systems` / `planets` : carte stellaire.
- `civilizations` : stats d’etat + meta (level, status, extinct, etc.).
- `events` : evenements appliques (avec metadata JSON).
- `marks` + `world_marks` : marqueurs globaux ou par civ.
- `ai_logs` : textes LLM (prompts, logs, analyses).
- `delayed_effects` : effets differes (qui s’appliquent dans le futur).
- `delayed_effects_applied` : trace d’effets differes appliques.
- `cycle_records` : enregistrement complet d’un cycle (JSON).
- `run_settings` : configuration persistante (ruleset, prompts, etc.).

Les donnees “vivantes” sont donc :
1) les stats (civilizations),
2) les evenements (events),
3) les marques (marks),
4) les logs LLM (ai_logs),
5) l’historique complet (cycle_records).

Le snapshot TXT (export) est un export plat a partir de ces tables.


6) Moteur de regles (RulesEngine)
---------------------------------
Le moteur est deterministic, avec un RNG seed. Il charge un catalogue d’evenements
`lib/events_catalog.json` et applique un ruleset pour choisir quoi tirer.

Les etapes internes (simplifiees) :
1. Pour chaque civ vivante : check stress/crise -> tirage d’evenements civ.
2. Tirage d’event global parfois (selon ruleset).
3. Application des events (deltas + marks + delayed_effects).
4. Application des delayed_effects arrives a maturite.
5. Test extinction (hard_extinction).
6. Test collapse (collapse_trigger -> collapse_outcome).

Les “AppliedEvent” contiennent :
- kind, scope, severity, target
- deltas (modif de stats)
- add_marks / remove_marks
- delayed_effects

Les stats sont clamp (0.0 -> 1.0). Chaque event modifie directement
les stats en memoire avant d’etre persiste.


7) Rulesets (comportement de la simulation)
-------------------------------------------
Trois rulesets majeurs :
- `harsh_realism` : logique dure (crises souvent fatales).
- `star_trek_lite` : progressions par phases (marks), optimiste.
- `cheat_utopia` : mode “cheat” (stabilisateur, ascension presque garantie).

Chaque ruleset peut redefinir :
- stress/crise,
- rolls mineurs/majeurs,
- chance d’evenements globaux,
- extinction dure,
- collapse,
- pondération des evenements.

Le mode cheat_utopia introduit :
- un “Guardian Stabilizer” qui remonte les stats,
- une progression rapide de phase,
- un attracteur post-scarcity,
pour forcer une trajectoire positive.


8) LLM : role, format, et parsing
---------------------------------
Le LLM (Ollama local) est optionnel.
Il ne prend pas de decisions. Il ecrit uniquement des textes.

Les points clefs :
- `LLMClient` (lib/llm.py) : fait les appels.
- Les prompts sont stricts (ex. LOG/GOD, TITLE/LOG/ANALYSIS).
- `lib/narrative_parser.py` parse et extrait les sections.
- Les textes sont stockes dans `ai_logs`.

En mode “No LLM”, le systeme genere des textes de secours
pour garder la structure.

Obituaries :
quand l’univers finit, une seule requete LLM resume chaque civ.
Le resultat est parse par sections “CIV:” et affiche dans une fenetre finale.


9) UI : fonctionnement et boucle
--------------------------------
L’UI est un `tk.Frame` (`AppUI`).
Elle affiche :
- carte des systemes,
- events + details,
- logs LLM par civilisation,
- status bar (cycle, events, civs),
- infos de bas de page (seed, mode, cycles).

La simulation tourne dans un thread worker (`_run_loop`).
Le thread envoie des evenements vers l’UI via une `queue`.
L’UI consomme la queue toutes les 100 ms.

Cela permet :
1) de ne pas bloquer l’UI,
2) d’afficher en streaming les chunks LLM,
3) de rafraichir les events apres chaque cycle.


10) Fin d’univers et “Obituary Window”
--------------------------------------
Quand toutes les civs sont mortes :
- `universe_ended` est mis a 1,
- le worker s’arrete,
- la fenetre principale se ferme (withdraw),
- une fenetre “And this was Transcendence” s’ouvre.

Cette fenetre affiche :
1) un texte poetique d’attente,
2) puis les obituaries LLM (ou fallback).

Un bouton “Quit” exporte le snapshot TXT final
et ajoute une section “== OBITUARIES ==”.


11) Export TXT (snapshot)
-------------------------
L’export snapshot (TXT) est fait dans `Database.export_snapshot`
et regroupe cycles, systems, planets, civs, events, logs, marks, effects, settings.

Le snapshot est un format “humain” et sert de trace finale.
Lors de la fin d’univers, les obituaries sont appended
au snapshot pour conserver la narration finale.


12) Flux complet d’execution (resume)
-------------------------------------
1. User choisit DB + ruleset + prompts.
2. Simulation init (seed + rules engine).
3. UI lance worker.
4. Worker boucle :
   - rules engine -> events -> persistence
   - LLM -> logs narratifs
   - UI refresh
5. Si universe_ended :
   - stop worker, show obituaries
6. Quit final -> export TXT.


13) Ce qui rend le systeme robuste
----------------------------------
- LLM est strictement optionnel.
- Output LLM est parse et valide, sinon fallback.
- Event effects et stats sont clampes.
- Persist complet de chaque cycle (cycle_records).
- Decouplage UI / worker par queue.


14) Extensibilite (ou ajouter des features)
-------------------------------------------
Quelques points faciles a etendre :
- Ajouter un ruleset dans `rulesets/`.
- Ajouter un prompt set dans `prompts/`.
- Ajouter une table ou mark dans `db.py`.
- Ajouter un nouvel event dans `events_catalog.json`.

Le systeme est concu pour evoluer sans casser les bases existantes,
car les settings sont persistants et les colonnes sont ajoutees au besoin.


15) Conclusion
--------------
TRANSCENDENCE est un simulateur regle‑d’abord, narration‑ensuite.
Il se comporte comme un moteur de jeu de role automatique, avec un LLM
utilise comme chroniqueur. La separation des couches (UI, simulation,
regles, persistence) permet de garder la logique claire et testable,
et de conserver un historique solide de chaque cycle.
