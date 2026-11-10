"""The pipeline engine: runs the cases of every unfinished campaign as jobs, in the control node process.

stage_graph.py          the stages and jobs of a case, idempotency keys, priorities, the case's progress
payload_builder.py      each job's payload from the config and the earlier results (inline or referenced)
campaign_context.py     a campaign's record, parsed config, stage graph and payload builder
case_machine.py         one job event applied to its case: moves, intents, drops, quarantine
coverage_controller.py  which cases a class starts, completes and cuts; backpressure
verdicts.py             verdicts, run records, calibration results, artifact references
retention.py            which artifact references a case keeps once judged
pipeline_queries.py     the engine's queries beyond the store API
pipeline_engine.py      the tick: events, desired and actual states, submissions, restart
engine_leadership.py    one engine per database: the advisory lock the leading engine holds

The module is loaded by the control node when it builds its control plane, not when its package is
imported, so importing the control node stays light.
"""
