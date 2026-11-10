"""Design space exploration: every functional equivalence class (FEC) of a specification within a scope.

The first step of the chain, before scene generation. Its input is one specification text (the metamodel and the
well-formedness constraints, the first part of a FEC specification) and a scope (how many target ships and static
obstacles). The Refinery model generator (image scenegems-design-space-exploration-subsystem, built from the pinned
Refinery commit) enumerates the models of it; each model is a FEC, a functional scenario the scene generation takes.

design_space.py                      the scope's syntax, the default specification, the pieces campaigns and jobs share
design_space_exploration_specs.py    the architecture description of the Capabilities page
"""
