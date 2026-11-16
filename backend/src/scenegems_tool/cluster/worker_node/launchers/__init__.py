"""Launchers: start and stop subsystems. The worker node daemon starts the pools, the simulation subsystem the stack of a run.

kubernetes_api.py         the one client of the cluster API: Deployments, pods and services in the cluster's namespace
docker_cli.py             thin wrappers around the Docker CLI (a run's stack, until a run is a pod)
compose_project.py        one compose project: its file and the CLI calls that run it
container_environment.py  environment between a launcher and the subsystem main it starts
pooled/                   long-lived services that serve many requests (design doc 4.3)
per_job/                  stacks created for one job or simulation and removed after it
"""
