# Key elements
- Core binary flag: exploring and feeding-breeding. The original jelly fishes all start in exploring mode; they know because memories are all blank; spawned jellyfish start in breeding mode and never explore.
- Self location tracking:
  - Always track the position relative to self’s starting position. Any location the jelly fish stores is in terms of self’s starting position.
  - At day 1, intialize this as `[0,0]` and store in memory
  - Each day, update memory: `self position = stored position (from last day) + current velocity (amount travelled since last day)`
- Circle center calculation (only original batch jellyfish do this):
  - Track whether we were in each zone the day before. When first entering and exiting either breeding, feeding, or predator zone, track current position and direction (which is the day when we detect we’ve crossed the circle border). whenever we have both entering and exiting information for a zone, calculate the center of that zone
    - For point on the circle, approximate using `position - half velocity` (both are recorded the day after crossing the border, so the velocity is the our velocity of the day before)
    - Then use trigonometry: midpoint of two points X and Y being M, distance from M to center can be calculated (it’s a right triangle where the hypotenuse is a radius)
    - Use entering / existing direction to disambigous the two possible circles centers.
    - Store zone of each center.
- Movement Plan:
  - A movement plan that the jelly fish follow repeatedly is defined by the number of days to travel in each direction. If the number is 0 for some then skip those depths. Allocate specific memory block for this:
    - E.g. number 8, 5, 4, 0 means we repeat the pattern of 8 days in depth 1 to 4.
    - We then store a single number to note which day in the plan we are currently in, and each day check if we need to change depth. Reset `current-day-in-plan` to 0 when a cycle of all depth finished.
- Plan action to destination:
  - When planning movement to a certain destination (e.g. self’s starting position, feeding zone cetner, breeding zone center), find a linear combination of current directions that take us there in the least amount of days. Then use that as a movement plan.
  - Note the torus shape of map, so calculate this combination five times (path can cross and wrap around any of the sides): once for actual destination within, once for wrapping around each edge
  - E.g. if destination is (100, 200), then we calculate for (100, 200), (1100, 200), (-900, 200), (100, 1200), (100, -800), because these are all the same point on the torus
- Loiter:
  - Loiter movement plan is a movement plan that results in the least amount of net drift. By this definition, in the degenerate case where all currents are in similar direction, loiter is achieved by following the slowest current (limit total # of days this loiter movement plan to 20 days)
- Always return `feeding action = true` when we are in feeding zone, and `breeding action = true` when we are in breeding zone and have capacity

# Algorithm
- First generation jellyfish action:
  - First, find direction of all depth
    - If memory has no direction for current depth (or in day 1 through 4), store that information, and switch to the next unexplored depth if any.
    - Memory stores: four numbers representing direction for each depth
  - Next, calculate the movement plan to grid search (comb) the map (this happens on day 4 when all current directions are known)
    - Use the surface (fastest) current direction as main current / vector
    - Of the three other current vectors, find the one with the largest component in the direction perpendicular to the main vector, this is the secretary current / vector
    - The search pattern is:
      - travel 25 days in main current (1000KM)
      - Travel N days in secondary current so that we travel at least 333KM in the direction perpendicular to main current
    - On this day, go to fastest depth to start following the movement plan
  - Now just follow the plan and search for feeding zone
    - Each day, check if self is in feeding zone, if so, go into next mode
  - Action at feeding zone:
    - Loiter in the zone
      - If arrived before next feeding season starts, also loiter until end of feeding season
      - if we drift out of the feeding zone and season hasn't ended, plot movement back to feeding zone center and continue loiter. 
      - whenever feeding season ends: if we have any breeding capacity, plot movement return to self’s start position in breeding zone; if have no breeding capacity, continue loiter at feeding zone center ( wait for next feeding season)

      - When exiting feeding zone for the first time, now have exit information for zone so use that with enter information to approximate and store feeding zone center position
  - Return to self’s starting position:
    - self’s relative position is relative to self’s starting position, so calculate movement plan using self’s starting position
    - When entering breeding zone, use enter/exit information to approximate breeding zone center and store that information
    - From now on, the jellyfish follows general jellyfish action
- General jellyfish:
  - General jellyfish behavior is simple: with the knowledge of breeding zone and feeding zone center, knowledge of all four currents, and starting with self in breeding zone
  - When in breeding zone:
    - If have capacity, loiter and breed;
    - if loiter results in drift out, or have no breeding capacity, or breeding season ends, plot course for feeding zone
  - When in feeding zone:
    - Loiter and (wait for season) and feed
    - If drifted out and have no breeding capacity, plot course back to feeding zone center and repeat
    - If drifted out and have breeding capacity, or feeding season ended, plot course to breeding zone center

# Implementation notes
- This iteration uses the maximum spec-allowed memory of 1024Byte
  - How many bytes to use for each value / data type should be calculated based on how many bytes we have in total. Write this as a place holder method, and we can use hard-coded data type lengths for now.
- First Implement a memory interface: create a data class that represents all the memorized states, and write write / read methods to read and update these states in the given bit array. The rest of the code only see this data class as the instance’s memory and do not directly interact with bit array
- If necessary, can use short data types for integers and floating points as we do not need very large integers or very accurate floating point positions.
  - Optional: current direction for each level can be stored as a integer to keep only the direction instead of full vector (e.g. using a X bits to divide circle in to $2^{16}$ directions is probably enough accuracy)
- Encapsulate seperaable functional code as methods, such as initial finding of four current directions, calculating plan (linear combination) for loiter / travel in a certain direction, etc.
- If implementing any math for more than a few lines, encapsulate in method even if not reusing for readability.

# Testing
- Write a method that evaluates the performance of current implementation by:
  - Run the simulation (using only our player’s jellyfish code) headless multiple times, using different (but seeded so repeatable) map generation, using initial initial size in `[10, 20, 40]`, lifetime in `[3, 4, 5]`, other arguments default
  - Record the result in a CSV: record run arguments, then total number in simulation, number surviving in the end, number eaten and number dying of old age.
# Clarifying questions (added by implementer)
Each item: **Q** = the question / unspecified detail, **Default** = what will be implemented unless told otherwise. Facts checked against `core/engine.py` are marked *(engine)*.

## A. Memory & sensing
1. **Q:** Default `-M` is 8 bytes; this design needs far more. What should happen if `memory_size` is too small for the layout?
   **Default:** Do not crash. Fall back to a trivial policy (stay at DEEP, always eat/reproduce). The evaluation script always passes `-M 1024`. A: yes, current implementation assumes -M 1024
2. **Q:** Position-update timing. *(engine)* `snapshot.velocity` is the current of the depth chosen *yesterday* (= what we actually drifted). But on an original's day 1 nothing has moved yet, and a newborn does **not** drift on its birth day, even though on its first `act()` `velocity` already reflects the parent's chosen depth.
   **Default:** Skip the position update when `age_days == 0` (originals' day 1). Also skip it on a newborn's first `act()` (`age_days == 1` and not an original). Otherwise do `position += velocity`. A: Accepted
3. **Q:** How do we store position precisely enough? Relative positions grow without bound, and quantization error accumulates daily.
   **Default:** Wrap the stored position to [-500, 500) km on each axis (torus) and store it as float32 (4 B/axis). Memory is plentiful, so this avoids drift from rounding. Zone centers are stored the same way. A: Accepted
4. **Q:** Zeroed memory makes "direction 0°" indistinguishable from "unknown".
   **Default:** Keep a known-flags bitmask (per-depth direction known, per-zone center known, etc.). Directions are stored as uint16 (2^16 steps per circle). A: accepted 
5. **Q:** Detecting offspring vs. originals. Offspring inherit the parent's memory, including its mode.
   **Default:** No special flag. The parent is always in "general" mode when it breeds, so offspring inherit general mode. Originals are identified by zeroed memory on day 1. Offspring keep the parent's coordinate frame, which is correct because they are born at the parent's position. A: accepted: any spawned instance, and any original instance that had returned to breeding zone are now in general mode 

## B. Zone-center estimation
6. **Q:** The algorithm says "When entering breeding zone, use enter/exit information to approximate **feeding** zone center". I assume this is a typo for **breeding** zone center (exit = when the original first leaves its start area, enter = on return).
   **Default:** Treat it as breeding zone center. A: Accepted and corrected 
7. **Q:** Near-tangent crossings: if the entry and exit points are very close, the center estimate is very sensitive to error. Also, the chord can come out > 400 km due to approximation error.
   **Default:** Clamp the half-chord to ≤ radius. If the chord is < ~60 km, discard the pair and wait for the next enter/exit pair (keep the latest entry). A: accepted 
8. **Q:** Disambiguating the two candidate centers.
   **Default:** Pick the candidate C for which `(C - P_enter)·v_enter > 0` (entering moves toward the center). If there is no entry velocity, use `(C - P_exit)·v_exit < 0`. A: accepted, keeping enter/exit velocity is for the purpose of disambiguating
9. **Q:** The predator zone center is tracked, but how is it used?
   **Default:** Compute and store it, but don't use it this iteration (no path avoidance). Optional later: avoid loiter anchors inside the predator zone.
  A: accepted
10. **Q:** Originals start *inside* the breeding (and possibly predator) zone, so their first event is an exit without a prior entry. Can a pair come from any later enter → exit (or exit → re-enter) of the same zone?
    **Default:** Yes. Any two border points of the same zone define a chord. Use the first valid pair and do not overwrite a known center. A: accepted. 

## C. Movement planning
11. **Q:** Torus images. The doc lists 5 images (original + 4 edge wraps), but the diagonal wraps (e.g. (1100, 1200)) can also be the shortest or only feasible route, e.g. when all currents lie in one half-plane.
    **Default:** Evaluate all 9 images (3×3). A: accepted 

12. **Q:** How do we solve "linear combination with least days"? Integer days cause rounding error (up to ~20 km per used current).
    **Default:** Solve the LP over nonnegative day counts. The optimum uses at most 2 currents, so enumerate pairs and pick the fewest total days. Round to integer days, then greedily fix the residual with the slowest currents if that reduces error. A: accepted. accepted some rounding error and keep overall travel plan iteration length reasonable 

13. **Q:** Is a travel plan executed once, or repeated like the comb/loiter plans? What happens when it finishes and we are not in the target zone?
    **Default:** Travel plans execute once, then the mode switches to "arrived" (loiter). If we finish a travel plan outside the target zone, re-plan from the current estimated position, at most 2 retries. After that, loiter anyway. A: accept. Travel plan execute once and recalculate if not arrived due to error. 

14. **Q:** Should travel re-plan daily (simpler, self-correcting) instead of storing a plan?
    **Default:** Store the plan, as the doc says, and re-plan only at the triggers listed in the algorithm. A: accepted, store the plan 


15. **Q:** Order of legs within a travel plan: do all of depth A, then all of depth B? Or interleave to stay near the straight line?
    **Default:** Do the legs sequentially in depth order (as in the movement-plan definition). A: accepted 

## D. Loiter
16. **Q:** What exactly is "least net drift"? Is it net drift per cycle or per day? Is there a constraint on max excursion within a cycle? (E.g. 10 days surface + 10 days in the opposite direction has zero net drift but a 400 km excursion, which leaves the zone.)
    **Default:** Pick nonnegative integer day counts with a total of 1..20 days. Minimize `|net drift per cycle|`, subject to a max excursion of ≤ 50 km along the cycle; ties go to the shorter cycle. If nothing meets the constraint, stay at DEEP. A: accepted 
17. **Q:** Loiter anchor. Loitering where we first detected the zone puts us at its edge, and repeated cycles accumulate residual drift.
    **Default:** If the zone center is known, travel to the center first, then loiter. While loitering, if the estimated position is > 100 km from the anchor (center, or the entry point if the center is unknown), re-plan back to the anchor. A: accept. when not knowing the center loiter anyway, drifting out would give info about center; other wise always try loiter at center. 
18. **Q:** What if the loiter spot is in the predator zone (5%/day death; also no breeding inside the overlap *(engine)*)?
    **Default:** Shift the loiter anchor 100 km toward the target-zone center (or away from the predator center if known).
    A: do nothing about predator zone in current iteration. leave #TODO for later 

## E. Timing / state logic
19. **Q:** *(engine)* `reproduction_capacity` is 0 all summer and is only assigned on day 181. So "drifted out of feeding zone and already have breeding capacity" can never be true during summer. Should we track feeding days ourselves?
    **Default:** Count summer eating days in memory: lifetime total for the 30-day maturity threshold, plus this summer's feed days. "Has capacity" during summer means `expected_capacity = feed_days // 10 ≥ 1`. After day 181, use the real `reproduction_capacity`. A: accepted 
20. **Q:** If drifted out of the feeding zone with ≥ 1 expected capacity mid-summer: leave for breeding, or go back and keep feeding for more offspring?
    **Default:** Go back and keep feeding until summer ends. Leaving early forfeits capacity, and breeding only happens in winter anyway. Leave mid-summer only if remaining travel time to the breeding zone would exceed the time until winter ends. A: accepted and corrected 
21. **Q:** If an original finds the feeding zone after summer has ended this year, should it loiter there until the next summer ends?
    **Default:** Yes. It needs feed days next summer to have capacity. A: yes. if self have no breeding capacity the goal is always to find, stay and wait or feed in feeding zone  
22. **Q:** Arriving at the breeding zone in fall (before winter): loiter until winter?
    **Default:** Yes, loiter until winter. Breed (one per day) while capacity > 0. When capacity reaches 0 or winter ends, travel to the feeding zone center. A: Accepted 
23. **Q:** Return target for originals: their start position (0, 0) or the breeding center?
    **Default:** Travel to the start position (the only known point). Once the breeding center is computed on entry, re-anchor loitering at the center. A: Accepted
24. **Q:** Can `eat` and `reproduce` simply always be `True`? *(engine)* Both are no-ops outside the right zone/season, and they have no downside.
    **Default:** Always return `eat=True, reproduce=True`. A: accepted 
25. **Q:** What if the comb never finds the feeding zone? 
    **Default:** Keep combing indefinitely (repeat the plan). A: accepted. By math (size of zone) combing will find zone eventually, but degenerate current directions can make it slow

## F. Search (comb)
26. **Q:** The comb spacing assumes a straight-line sweep. On a torus, a 1000 km run at a non-axis angle doesn't return to the same line, so coverage isn't guaranteed. Is the heuristic acceptable as-is?
    **Default:** Yes, implement as described. The secondary current is chosen by the largest absolute perpendicular component (either sign). N = ceil(333 / |perp speed|), capped at 60 days. A: accepted. the combing pattern doesn't need to return to the same line 
27. **Q:** On day 4 the comb starts at the "fastest depth". Should the first leg be the main (surface) leg?
    **Default:** Yes: the plan is [main 25 days, secondary N days], repeated, starting at day 0 of the main leg. A: accepted 

## G. Testing / evaluation
28. **Q:** What is "total number in simulation"?
    **Default:** Initial J + total births. The CSV also records peak population and births blocked. A: accepted. total number of simulation is combination of all seeds and arguments (see below)
29. **Q:** How many seeds, and how many days? Where should the script and CSV live?
    **Default:** 5 seeds (e.g. 1..5) × J ∈ {10, 20, 40} × S ∈ {3, 4, 5} = 45 runs. Use `-T 3600` (the default) and `-M 1024`. Run it via `uv run main.py --players 3 --json` as a subprocess. Script: `players/group3/evaluate.py`; output: `players/group3/results/eval_<timestamp>.csv`. A: accepted. 
