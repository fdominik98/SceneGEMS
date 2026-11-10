"""The control node's artifact store (P4.3): content-addressed, gzip-compressed files of large job data.

artifact_store.py       the interface, errors and the write contract (MinIO may implement it later)
file_artifact_store.py  the implementation on the control node's artifact volume
recorded_artifacts.py   files and their Postgres records in step: upload, read, sweep
"""
