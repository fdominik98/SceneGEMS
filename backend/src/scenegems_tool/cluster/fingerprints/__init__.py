"""Build fingerprints of the container images, shared by the node and the master.

    labels.py      read the fingerprints a machine's images carry (node side, Docker API)
    comparison.py  compare a node's fingerprints with the required ones
    components.py  the component catalog: what a node offers and the images of each component, so the
                   required fingerprints of a job and a node

A fingerprint is computed by deploy/scripts/docker-common.sh and stored in the built image as the
label org.scenegems.fingerprint. Image names are the full tags, for example
scenegems-scenario-execution-subsystem:latest.
"""
