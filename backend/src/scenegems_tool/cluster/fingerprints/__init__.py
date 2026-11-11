"""Build fingerprints of the container images, shared by the worker node and the control node.

    labels.py      read the fingerprints a machine's images carry (worker node side, Docker API)
    comparison.py  compare a worker node's fingerprints with the required ones
    components.py  the component catalog: what a worker node offers and the images of each component, so the
                   required fingerprints of a job and a worker node

A fingerprint is computed by deploy/scripts/docker-common.sh and stored in the built image as the
label org.scenegems.fingerprint. Image names are the full tags, for example
scenegems-simulation-subsystem:latest.
"""
