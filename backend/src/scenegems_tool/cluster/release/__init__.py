"""The release bundle: what a deployment tool installs on a machine to run a control node or a worker node.

SceneGEMS does not deploy itself. An external tool (Machine Hub) sets up the VPN between the
machines and installs a release bundle on each machine it is given a role for. The bundle
holds no source code, only what the machine runs:

    release.json        revision, every image with its ID and fingerprint, and the roles
    stacks/<role>/      the compose file of each role (control node, worker node)

    manifest.py   the release file: read, write, validate; the control node reads its expected
                  image fingerprints from it
    roles.py      the roles of a SceneGEMS cluster: stack, images, env, generated secrets,
                  setup commands (the contract with the deployment tool)
    bundle.py     write a bundle from the built images of this checkout
    __main__.py   command line used by deploy/scripts/build.sh --release
"""
