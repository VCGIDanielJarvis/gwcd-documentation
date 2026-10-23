# Geocoding: Geocoded vs. Non-Geocodable Data

## Process

1. Each record's address is concatenated (`Address1, City, VT, Zip`) and
   geocoded against the state's E911 composite address locator.
2. Any record whose address **fails** to geocode is retried using **just the
   town name**, geocoded to that town's **centroid** point instead.
3. Only a record that fails **both** steps (no usable address, and no
   recognizable/geocodable town name) is dropped from the geocoded/mapped
   product.
4. All surviving points (address-level matches + centroid fallbacks) are
   spatially joined to town boundaries to assign a `TOWNNAME`.

**Practical implication**: because of the centroid fallback, the overwhelming
majority of records end up with a town assignment even when the home address
itself can't be pinpointed. Geocoding failure (a record with no `TOWNNAME` at
all) should be rare — it requires the town/city field itself to also be
unusable (blank, out-of-state, unresolvable typo not covered by the alias
table, etc.).

## Is there a single view with both geocoded and non-geocodable results?

Not as a single ready-made table, but it's straightforward to assemble:

| Table | Geocoded? | Filtered to private-water scope? | Use for |
|---|---|---|---|
| `GroundwaterChemistry_GWCDrawdata` | No | No | **Full, unfiltered dataset** — best for state-level totals/rates that don't need geometry or town-level slicing |
| `GroundwaterChemistry_GWCDPoints` | Yes (address or town centroid) | Yes | Town-level slicing with unsuppressed counts — best source for a grant-reporting dashboard |
| `GroundwaterChemistry_GWCDPointTableExternal` | Yes | Yes, plus deduplicated + suppressed (<20 samples/group hidden) | What the public app displays — don't use this for totals, you'll undercount |

If you need one dataset with **both** full records and a town flag, join
`GroundwaterChemistry_GWCDrawdata` to `GroundwaterChemistry_GWCDPoints` on
`Record_uid` — this gives every raw record, with a `TOWNNAME` where one could
be determined and NULL where it couldn't.

For a dashboard that needs **both** state-level and town-level views: start
from `GroundwaterChemistry_GWCDrawdata` (or the raw SQL source) for the
state-level numbers — it needs no geocoding — and use
`GroundwaterChemistry_GWCDPoints`'s `TOWNNAME` field for the town-level slice.
