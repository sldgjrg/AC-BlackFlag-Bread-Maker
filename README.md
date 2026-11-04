Please excuse the lack of version history; this project solely resided on my local storage prior to the MIT maker Portfolio.

Thank you!

Below is a more in-depth explanation of the projects demonstrated in my Maker Portfolio Video. I apologize for the inconsistency; I wasn't able to discuss these concepts due to the time limit

**VEX Robotics — Motion Control & Autonomous Systems**

**The engineering behind the robot**

This is a more technical explanation of some of the software I worked on for our VEX Robotics robot. I couldn't fit most of it into my MIT Maker Portfolio video, and honestly, a lot of the interesting stuff happened behind the scenes, usually when something wasn't working.

My main focus was improving how the robot moved and making autonomous programming faster and more reliable. That eventually led to experimenting with sigmoid-shaped velocity profiles, automated PID tuning, arc turns, and a system for recording autonomous routines through manual driver control.

Most of the programming was done in C++ using VEX's motor encoders, inertial sensor, and drivetrain controls.

**1. Sigmoid Velocity Profiling**
   
**The problem**

Initially, our robot's movements were pretty jerky. Applying high motor voltage immediately caused abrupt acceleration, while braking too aggressively could make the robot overshoot, snap backward, or disturb its positioning.

This was especially frustrating during autonomous routines, where small errors could accumulate across multiple movements.

We wanted something that would accelerate smoothly, maintain speed, and decelerate as it approached its target without wasting unnecessary time.

**Our approach**

We experimented with sigmoid-shaped velocity profiles to replace abrupt changes in motor commands with smoother acceleration and deceleration.

A logistic sigmoid follows the general form:

f(x) = 1 / (1 + e^(-kx))

Here, k controls how sharply the function transitions.

The important part was adapting the curve to the robot's actual movement. Instead of treating acceleration as a fixed delay, our distance-based implementation tracked encoder progress and adjusted the commanded drive voltage based on how far the robot had traveled relative to its target.

We used sigmoid-shaped transitions for acceleration and braking. The profile needed to behave differently for short and long movements, since a robot traveling a few inches shouldn't spend the same amount of time accelerating as one traveling several feet.

We also incorporated heading feedback from the inertial sensor. If the robot started drifting left or right, the controller could apply different corrections to the two sides of the drivetrain.

Conceptually, the system worked like this:
1. Read the target travel distance and reset the relevant encoder measurements.
2. Calculate movement progress from the drivetrain encoders.
3. Use the acceleration or deceleration portion of the profile to determine the desired motor command.
4. Calculate heading error and apply PID corrections to the left and right motors.
5. Continue updating the commands as the robot approaches its destination.
6. Stop or hold once the movement reaches its completion conditions.

**What made it difficult**

Getting a nice-looking curve was much easier than getting the physical robot to follow it.

We had to deal with motor friction, inertia, changing travel distances, heading drift, and the fact that a command that worked well over a long distance could behave terribly over a short one.

Some versions slowed down too early. Others braked too late, overshot the destination, or corrected too aggressively near the end.

We spent a lot of time changing the shape and scaling of the profiles, adjusting the lower motor commands needed to overcome friction, and testing different stopping behaviors.

My contribution: I primarily implemented the profiling system in code. Jaden and Zuhayr worked closely with me on the mathematics, refining the curves, and identifying problems in my earlier implementations. It was very much a collaborative process, and the final approach benefited from all three of us repeatedly testing and questioning it.

**2. Automatic PID Tuning**

**Why I wanted to automate it**

PID control is useful for correcting errors in movement and turning, but finding good gains manually can be tedious.

You change a value, run the robot, observe how it behaves, make another adjustment, and repeat. Sometimes one change improves the response in one situation while making it worse in another.

I started wondering whether I could automate some of that process.

Rather than spending an entire session guessing gains, I wanted the robot to run controlled tests, measure its own behavior, and calculate or recommend better parameters.

**Tuning methods I explored**

**Ziegler–Nichols**

One approach was based on finding the ultimate gain (Ku) and ultimate oscillation period (Pu).

The basic idea was to run the controller using proportional control, increase or search through the gain until a suitable sustained oscillation could be identified, and estimate the oscillation period.

From those measurements, the classical Ziegler–Nichols method provides initial PID parameters.

My implementation experimented with detecting oscillation through repeated heading-error crossings and examining how consistent the resulting peaks were. I also explored searching through proportional gains rather than simply making arbitrary adjustments by hand.

**Tyreus–Luyben**

I also explored Tyreus–Luyben tuning rules, which use the same general ultimate-gain and oscillation-period information but produce more conservative controller parameters.

This was useful for comparing the tradeoff between aggressive response and stability. A robot that reaches its target quickly but oscillates around it isn't necessarily performing better.

**Åström–Hägglund-inspired testing**

I experimented with oscillation-testing ideas inspired by the Åström–Hägglund relay-feedback approach.

The goal was to obtain useful information about the robot's response through controlled oscillatory behavior rather than depend entirely on manually selected gains.

These methods gave me several ways to generate candidate PID values, but none guaranteed a perfect result on the real robot.
Automated evaluation and refinement
Beyond calculating gains from established tuning rules, I explored testing candidate parameters and evaluating how the robot actually responded.

Some of the measurements I focused on were:
- Settling time: How long the robot took to reach and remain near its target.
- Overshoot: How far the robot traveled or turned beyond the intended position.
- Residual error: How close the final position or heading was to the target.
- Oscillation: Whether the robot continued correcting back and forth instead of settling.
  
This was one of my favorite parts of the project because it turned tuning into another programming problem.

The controller was no longer just following instructions. I was experimenting with ways for the software to evaluate its own performance and help improve the next test.

It still required human judgment. Different tuning rules prioritized different behaviors, and the fastest response wasn't always the most reliable.

My contribution: The PID autotuning work was primarily mine, including researching the methods, implementing the tests and calculations, and experimenting with automated parameter selection.

**3. Arc Turns**

**Making autonomous routines faster**

One thing that bothered me about our autonomous routines was how much time could be wasted on unnecessary stops.

A typical sequence might involve driving straight, braking to a stop, rotating to face another direction, and accelerating again.

That works, but it isn't always efficient.

Jaden and I worked on arc turns so the robot could combine forward movement and rotation into one continuous maneuver.

**How they worked**

Instead of treating translation and rotation as completely separate actions, we experimented with changing the relative motor outputs on the left and right sides of the drivetrain while the robot was moving.

A differential-drive robot turns whenever its two sides travel at different speeds. By controlling that difference while maintaining forward motion, we could make the robot follow a curved path.

We also experimented with blending heading corrections across the progress of a movement rather than applying the entire heading change immediately.

This made it possible to connect portions of an autonomous routine more naturally, reducing the number of complete stops.

The hard part was balancing speed with accuracy. Turning too aggressively could throw off the intended path, while turning too gently could leave the robot misaligned at its destination.

We tested different combinations of translation, rotation, and heading correction to make the movements practical for competition.

My contribution: Jaden and I collaborated on the arc-turn implementation and its refinement.

**4. Driver-Recorded Autonomous Routines**

**Because hardcoding everything gets tedious**

Traditional autonomous programming often involves specifying movements individually, testing the sequence, and repeatedly changing distances, angles, or timing.

I wanted a faster way to prototype routines.

My idea was to let someone drive the robot through the desired sequence manually, record those movements, and use that recording as the basis for autonomous playback.
Recording and replaying movement

I was in the process of developing a system that captured driver-control movements as a sequence that could be replayed without requiring every action to be written manually.

The purpose was to preserve the order and timing of the driver's commands so that a rough autonomous routine could be created through demonstration instead of starting entirely from hardcoded instructions.

This was especially useful as a development tool. We could try a route manually, record it, and use that starting point for further adjustments.

Of course, replaying inputs isn't the same thing as guaranteeing identical physical movement. Motor behavior, battery conditions, friction, and small differences in starting position can all affect the result.

That limitation made the project interesting because it raised another question: how much of an autonomous routine can be learned from a demonstration, and how much still needs sensor feedback and correction?

The recording system was my attempt to reduce repetitive programming and make autonomous experimentation more accessible.

My contribution: I worked on the driver-recording and autonomous-replay system independently.

**5. Additional Motion-Control Experiments**

**Several smaller control problems came up while working on the main systems.**

Heading correction: I used inertial-sensor feedback to measure heading error and correct differences between the two sides of the drivetrain. This mattered particularly during longer movements, where minor drift became noticeable.

Predictive braking and stopping behavior: I experimented with slowing the robot before it reached its target rather than waiting for an error to change sign. Much of this involved finding a balance between stopping early and overshooting.

Motor friction compensation: Small motor commands don't always produce meaningful movement. I experimented with minimum command thresholds and compensation for this effect, especially near the end of a movement.

Oscillation and overshoot control: Some of our control experiments had a frustrating habit of reaching the target and then correcting past it, sometimes repeatedly. I experimented with damping, correction limits, and settling conditions to reduce that behavior.

Testing and debugging: We repeatedly tested different movement distances, turning angles, and controller parameters. One important lesson was that an algorithm could behave perfectly in calculations and still perform badly once connected to motors, wheels, sensors, and an actual competition field.

I also worked on drivetrain utilities and diagnostic functionality, including monitoring motor behavior and improving the workflow for testing and making adjustments.

**6. Navigable VEX Brain Screen**
   
I also built a navigable interface on the VEX Brain itself. I wanted the Brain's display to be another portion of the robot that we could utilize, sort of like usable real estate. Rather than being mostly static, we figured it could assist us in debugging and allow us to be more competitive as a team. 

It allowed us to preview autonomous routines based on the route that they observed, so that we could load the correct one each time without mistake. It also assisted us in scenarios where the controller was either missing or unusable-- such as when I would take the robot home and forget to bring the controller --so that we could test movements without having access to joysticks or buttons.

The interface let us navigate between screens on the robot instead of having to cram everything onto a single display window. The biggest challenge was making the interface useful during actual testing, when you want to get to the relevant information quickly rather than scroll through a wall of text or reconnect to a laptop for every little thing.

It was a smaller project than the motion-control code, but it came from the same frustration: even a simple inconvenience is an excuse to build a better tool.

My contribution: I developed the navigable Brain-screen interface.

**Collaboration and Credits**

This project was developed in unity with my friends and teammates.

We collaborated closely on the robot's motion-control systems, particularly sigmoid profiling, mathematical refinement, implementation, and testing. Jaden and I also worked together on arc turns.

I took primary responsibility for coding the sigmoid profile, developing the automatic PID tuning systems, and implementing driver-recorded autonomous routines.

The robot itself, its autonomous performance, and the process of improving it were team efforts. The software described here is the portion I focused on most heavily.

**Black Flag — Computer-Vision Checkers Bot**
  
**An overcomplicated solution to a very small problem**

I wanted to automate checkers inside Assassin's Creed IV: Black Flag. I could have just played the game myself, but writing a program that could look at the screen, interpret the board, decide what to do, and click the right square sounded a lot more fun.

I developed the bot independently in Python. Unlike a normal checkers program, it couldn't directly access a clean representation of the board. It had to work from whatever the game was rendering on the screen.
1. Reading the game screen
The general pipeline was:
1. Capture the current screen.
2. Find the checkers board in the image.
3. Interpret the board's position and visible game state.
4. Determine the move to make.
5. Translate that move into screen coordinates.
6. Execute the move through automated mouse input.
7. Continue checking the game state to see what happened.
The coordinate conversion was more complicated than it sounds. A move selected in board coordinates still had to land on the correct location in the game window. An offset or inaccurate board detection could cause a perfectly reasonable move to turn into a completely unreasonable mouse click.

**2. The day-night cycle problem**

One of the most annoying problems was that Black Flag has a dynamic day-night cycle. The same board could look noticeably different depending on the time of day, shadows, lighting, and contrast.

A visual match that worked in one situation could fail once the lighting changed. The bot sometimes couldn't even locate the board, so improving move selection didn't matter if the image-processing stage failed first.

I spent a lot of time debugging how the bot recognized the board and trying to make the detection less sensitive to those visual changes. It was a good reminder that a game screen is not a neat, controlled dataset.

**3. Performance optimization**

I also had to be pretty aggressive about optimization. The program needed to repeatedly process screenshots, locate the board, make a decision, and send inputs without spending so much time processing that the automation became impractical.

That meant paying attention to the expensive parts of the pipeline and avoiding unnecessary work wherever possible. Recognition accuracy and responsiveness were constantly competing: a more thorough search could help find the board, but spending too long on each frame made the bot feel slow.

**4. Actually interacting with the game**

Mouse automation added another set of problems. Even after the program decided on a move, the game still had to receive the click in the correct place and at the correct moment.

The most frustrating bugs weren't always bad decisions. Sometimes the board wasn't detected. Sometimes the coordinate mapping was off. Sometimes the bot needed to retry its search because the game had changed visually since the previous screenshot.

The project ended up being less about writing a checkers player and more about making several unreliable components work together reliably enough to play.

My contribution: I developed the bot independently, including the Python automation, screen analysis, board detection, move selection, coordinate mapping, performance improvements, and debugging.

**Al Faqih — Multilingual Religious Narration Search**

**Making a large collection of texts easier to search**

Al Faqih is a search platform I built to help people find relevant religious narrations from natural-language questions. Instead of requiring someone to know the exact wording of a passage, I wanted them to be able to describe the subject they were looking for (or the question they wanted to ask) and get related texts back with their sources.

The collection contains roughly 22,000 English/Arabic narrations, structured with volume, book, chapter, and narration information. The main challenge was making search work by meaning, not just by matching keywords.

1. Preparing the dataset

I started with a somewhat unstructured collection of narration records, and with permission, scraped them before preparing them for retrieval. Each search result needed to carry more than its text: it also needed the contextual metadata and a link back to the source so the user could inspect the original passage.

Preparing the data consistently was important because the retrieval model and the interface both depended on having predictable records. A result was only useful if the correct narration and its reference stayed together through the entire pipeline.

My ram would also sometimes suffer from having to open such an enormous file. 

Unicode characters, improper textual formatting, and involuntary splicing were some of the main challenges in this part.

**I first attempted to train my own local models to accomplish the tasks below, but my hardware limited my ability to do so. Although utilizing a cloud-GPU service worked, computational costs rose to a level greater than I could support** 

2. Semantic embeddings and vector search

For retrieval, I used a pretrained sentence-embedding model, sentence-transformers/gtr-t5-large, to represent narration text as vectors.

I normalized the embeddings and built a FAISS IndexFlatIP index. Because the vectors are normalized, inner-product search can be used to rank results by cosine similarity.

At query time, the system can convert the user's question into an embedding and retrieve narrations whose meanings are similar to the question, even if the exact words don't match.

This was a lot more useful for open-ended searches than relying entirely on literal keyword matches.

I also experimented with automatic NLP or LLM processing of the user's query and converting it into a prompt which would more closely align with what the vector database expected. It would allow users to frame their prompt however they wished, and ensure there would be no quality drop.

3. Reranking the results

Vector similarity is a good first pass, but a result that looks close in embedding space isn't always the best answer to a specific question.

To improve the ordering, I added a second stage using the pretrained cross-encoder cross-encoder/ms-marco-MiniLM-L-6-v2.

Instead of scoring the query and narration separately, the cross-encoder considers them together and produces a relevance score for the pair. I used those scores to rerank candidate results before showing them to the user.

The combination of a fast first-stage vector index and a more selective reranking stage was a practical compromise between retrieval quality and response time.

4. Multilingual queries and explanations

I wanted people to be able to ask questions in different languages even though the main indexed collection was in English.

I added language detection and translation as part of the query-processing workflow, allowing the system to search against the collection and return information in the user's target language.

I also integrated an LLM for optional explanations and follow-up questions about retrieved passages. The underlying narrations and their source references remain the important part: generated explanations are separate from the source texts.

5. Backend, frontend, and deployment

Originally, the backend was deployed on an Oracle server within a docker container, using my local machine as a VPS to serve the endpoint. It was hindered by free usage limits, and the fact that computation would take a very long time.

As it had a fixed amount of workers, (which would parallelize when needed), if multiple users made queries around the same time, it wouldn't be able to dedicate a substantial amount of processing power to either one. Often, queries would be placed on a "waitlist" until previous ones completed.

A hard part was configuring everything to communicate over HTTPS, with security keys that had to be adjusted and replaced about every 3 months with PuTTY. Part of the engineering work was simply making the different pieces run together reliably outside my development environment.
