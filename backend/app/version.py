"""The user-facing PLM2 ECR version.

One string, bumped by hand, and only when a main feature changes what the
people working a change have to know. Never on a deploy. It is what the
training record means when it says somebody was trained "on ECR 1.0": the
audit answer to "trained on what, exactly", long after the screens have moved
on (same rule as TWOS, app/version.py there).

It is snapshotted onto a training sign-off at the moment the practical tasks
are passed, and onto every published training version. Bumping it is usually
the same moment new training material is published for the roles the change
affects (Training, Records, "Publish a new version").
"""

#: "ECR <major>.<minor>". Major changes when the change flow itself changes;
#: minor when a feature is added inside that flow.
SOFTWARE_VERSION = "ECR 1.0"
