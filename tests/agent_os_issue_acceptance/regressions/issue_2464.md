# Regression contract — #2464

Authority/currentness-affecting evidence flags in the finite batch merge coordinator must require exact built-in booleans. Truthy strings, integers, and custom objects must fail closed rather than being interpreted as provider availability, semantic conflict, or successful merge evidence.
