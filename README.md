# JWST Galactic Center Survey dashboard

A lightweight status dashboard for [JWST Program 10678](https://www.stsci.edu/jwst-program-info/visits/?program=10678), **The JWST/NIRCam Legacy Survey of the Galactic Center**.

The site is designed for GitHub Pages at:

<https://ashleythomasbarnes.github.io/jwst_gc_dashboard/>

## What it shows

Each STScI visit is shown as a field card with its target, exact visit status, observation and visit numbers, observing modes, charged time, and either its Plan Window or actual start/end time.

The colours group the original STScI status without replacing its wording:

- Grey: Flight Ready and other neutral or inactive states
- Yellow: Scheduled
- Green: Executed, Collecting, Archived, or Completed
- Red: any status containing Failed, including `Failed - Archived`

## Update the data locally

The updater uses only the Python standard library:

```bash
python3 scripts/fetch_visits.py
```

Run the tests and serve the site locally:

```bash
python3 -m unittest discover -s tests -v
python3 -m http.server 8000
```

Then open <http://localhost:8000>.

## GitHub Pages automation

`.github/workflows/update-dashboard.yml` runs at 06:17 UTC each day, on pushes to `main`, and when started manually. It tests the parser, downloads the public STScI XML report, validates the generated JSON, commits the refreshed snapshot, and deploys the static site.

For the initial publication:

1. Create the public repository `ashleythomasbarnes/jwst_gc_dashboard` and push this checkout to `main`.
2. In the repository, open **Settings → Pages**.
3. Under **Build and deployment**, select **GitHub Actions** as the source.
4. Run **Update and deploy dashboard** from the Actions tab if the first push did not already start it.

If a fetch or validation step fails, the workflow stops before deployment, leaving the previous working site online.

## Data source

The dashboard is an independent view. The authoritative visit information and status definitions are maintained by the [Space Telescope Science Institute](https://www.stsci.edu/jwst-program-info/visit-help/?program=10678#status).
