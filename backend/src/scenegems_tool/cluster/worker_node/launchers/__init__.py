"""Launchers: start and stop subsystem containers. The worker node daemon starts the pools, the simulation subsystem the stack of a run.

docker_cli.py             thin wrappers around the Docker CLI
compose_project.py        one compose project: its file and the CLI calls that run it
container_environment.py  environment between a launcher and the subsystem main it starts
pooled/                   long-lived services that serve many requests (design doc 4.3)
per_job/                  stacks created for one job or simulation and removed after it
"""
