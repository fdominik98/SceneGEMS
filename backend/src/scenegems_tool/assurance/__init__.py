"""Assurance: campaigns over the functional scenario catalog and the per-case pipeline.

    campaign/   the campaign config (model, YAML loading, hash, case seeds), the class
                catalog of functional scenarios, validation against the catalog and the
                vessel stack resolver
    cli/        the campaign command line, `python -m scenegems_tool.assurance` (operator API client)
    pipeline/   the pipeline engine that runs a campaign's cases as jobs (P4.4)

Campaign state lives in the control node's database (persistence/stores); this package decides
what a campaign is and how it advances.
"""
