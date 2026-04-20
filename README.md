# treningsdata

Automatisk synk av Strava-aktiviteter — kjører daglig via GitHub Actions, commits JSON-dumper tilbake til dette repoet.

## Hvordan det fungerer

1. GitHub Actions kjører `scripts/fetch_activities.py` hver morgen ca. kl. 07:00 Oslo-tid.
2. Scriptet bruker refresh-tokenet til å hente en fersk access-token fra Strava.
3. Det spør etter aktiviteter nyere enn den siste vi har, og laster ned full detalj for hver.
4. Nye aktiviteter lagres som `data/activities/{id}.json`.
5. `data/summary.json` bygges opp på nytt — en kompakt, nyeste-først-indeks.
6. Eventuelle endringer committes og pushes automatisk.

## Mappestruktur

```
.
├── .github/workflows/sync-strava.yml   # daglig GitHub Actions-jobb
├── scripts/fetch_activities.py         # henter og lagrer
├── data/
│   ├── activities/{id}.json            # full aktivitetsdump
│   └── summary.json                    # kompakt indeks
└── README.md
```

## Secrets som kreves i repoet

Legges inn under **Settings → Secrets and variables → Actions**:

- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`

## Kjøre manuelt

Fra GitHub: **Actions → "Sync Strava activities" → Run workflow**.

Lokalt (for debugging):
```bash
export STRAVA_CLIENT_ID=...
export STRAVA_CLIENT_SECRET=...
export STRAVA_REFRESH_TOKEN=...
python3 scripts/fetch_activities.py
```

## Merknader

- Første kjøring henter siste 90 dager. Deretter er det inkrementelt.
- Strava rate-limits er 100 requests/15 min og 1000/døgn — scriptet holder seg langt under.
- Hvis du tilbakekaller tilgangen i Strava (Settings → My Apps), må refresh-tokenet regenereres.
