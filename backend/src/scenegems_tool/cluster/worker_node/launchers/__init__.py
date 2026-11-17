"""Launchers: start and stop subsystems. The worker node daemon starts the pools, the simulation subsystem the pod of a run.

kubernetes_api.py         the one client of the cluster API: Deployments, pods and services in the cluster's namespace
container_environment.py  environment between a launcher and the subsystem main it starts
pooled/                   long-lived services that serve many requests (design doc 4.3)
per_job/                  the pod of one simulation run, created for it and removed after it
"""
