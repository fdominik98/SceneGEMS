"""The control node's database: worker node registry, job store, campaigns and their results on Postgres.

Postgres only: the job store relies on JSONB and SELECT ... FOR UPDATE SKIP LOCKED.

    database.py        SCENEGEMS_DATABASE_URL, engine, session factory, transaction scope
    clock.py           the UTC clock the stores read, replaceable in tests
    canonical_json.py  canonical JSON and its sha256, for config hashes and calibration keys
    migrate.py         Alembic configuration kept inside the package, upgrade, command line
    schema/            SQLAlchemy tables: worker nodes and jobs; campaigns, classes, cases, pipeline jobs, cursor,
                       run records, verdicts, campaign events; artifacts, references, calibration results
    migrations/        Alembic environment and revisions
    stores/            transactional primitives the control node's registry, scheduler and pipeline engine call
"""
