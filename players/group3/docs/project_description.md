Project 4: Jellyfish
Jellyfish can travel extraordinary distances, which is somewhat surprising given how slowly they appear to move. It seems that they take advantage of ocean currents to move between different zones that are suitable for the season. Our project is motivated by these migrations, with a focus on how jellyfish might navigate. In particular, jellyfish need to be in the feeding zone during summer in order to accumulate enough resources to spawn offspring in the breeding zone in the winter. During this migration, they might cross the predator zone, where they run the risk of being eaten.

The ocean is 1000x1000km, and to make life simple we'll assume that the topology of the ocean is a torus, i.e., flow off the right edge wraps around to the left edge, and flow off the top edge wraps around to the bottom edge. There is no land for the jellyfish to worry about. The feeding zone is a circular region of radius 200km located somewhere in the ocean (possibly wrapping around the edges), while the breeding zone is a disjoint circular region of radius 200km. The predator zone is another circular region of radius 200km. The predator zone and the breeding/feeding zones may overlap.

The ocean is filled with currents. A current is a band of water of constant depth that moves in unison at a fixed velocity. Current depths can be one of "surface", "shallow", "medium" and "deep". Because currents have different depths, they do not interfere with each other. There are four currents in total (one per depth) and each may have a different speed and direction of water flow.

Jellyfish can move between depths, and can thus switch between currents to get where they want to go. Jellyfish cannot, however, swim laterally. The only way they can achieve lateral movement is by going with the flow of the current.

Jellyfish also have limited memory. We'll try different memory sizes, anywhere between 1 byte and 1024 bytes. The simulator will give you access to an array of the appropriate size that the jellyfish can modify as it sees fit. One of the project goals will be trying to get successful jellyfish lifecycles with as small a memory as possible. For obvious reasons, your code will not be permitted to retain information between turns: the simulator-provided array is the entire jellyfish memory.

When jellyfish spawn, they have the capacity to produce 1 offspring for every 10 days they spent eating in the feeding zone during the previous summer. They can produce only one new offspring each day, and that has to occur in the breeding zone. Offspring will receive a copy of the parent's memory as their initial memory.

The breeding requirement that feeding happens during the previous summer reduces the effectiveness of certain “safe” strategies like staying in the feeding zone for many years, then moving to the breeding zone.

The calendar is 360 days with four 90-day seasons (spring, summer, fall, winter).

Jellyfish have limited sensory capabilities. They know:

their depth
their direction and speed of movement (they can sense the current by observing fixed reference points such as the sun or the ocean floor)
whether they are in a feeding zone or breeding zone or neither
whether they are in a predator zone
the current day of the year, and the current year
the day and year of their birth
what's in their memory
their remaining reproduction capacity
Jellyfish have a fixed lifetime of S years, i.e., S*360 days. S does not have to be an integer, and is a parameter of the simulation.

A jellyfish needs to eat for 30 days before it is large enough to reproduce. So the first 30 days of eating don't count towards reproduction. The initial 30 eating days could be split across multiple summers.

During a turn, which corresponds to the start of a day, a jellyfish may do one or more of the following:

move to a new depth (or stay at the same depth)
alter the memory
eat (if in the feeding zone during summer)
reproduce (if in the breeding zone during winter and the jellyfish has previously eaten sufficiently)
All of these choices can be based on what they can sense. The simulator will make the appropriate changes according to the jellyfish actions, and will move the jellyfish according to the current at the chosen depth. If the jellyfish starts in a predator zone, then there is a 5% chance that the jellyfish will be eaten on that turn.
The top level current has a speed of 40km/day. The second level current has a speed of 20km/day. The third level current has a speed of 10km/day. The fourth, deepest current has a speed of 5km/day. These speeds are fixed across simulations, but the direction of each current will be chosen uniformly at random for each run. The simulator will use a random number seed, so that simulations can be repeated with the same directional settings. We'll assume that eating and breeding can happen at any depth.

At the start of the simulation, day 1 of year 1, a small number J of jellyfish are born at random locations in the breeding zone. Initially, the jellyfish memory will be initialized to zero. Your goal is to sustain, and hopefully grow the jellyfish population. Some possible goals:

Long-term survival, i.e., the population has not gone extinct after some large number of turns.
Fast growth. Time to achieve a large population, e.g., 10J or 100J.
Since there is no interaction between jellyfish (e.g., they don't compete for food) the simulator will be able to run multiple groups in the same ocean at the same time, to visualize each group's strategy in parallel.

Some things to think about:

What is the best way to use your limited memory?
How might a jellyfish achieve movement in a direction not exactly aligned with any current?

