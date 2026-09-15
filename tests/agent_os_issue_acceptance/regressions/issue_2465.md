# Regression contract — #2465

Merge-attempt and lifecycle-mutation acknowledgement inputs must be exact booleans. Non-boolean truthy values must never advance the coordinator to readback as if a mutation was accepted.
