"""Build the standalone, transcript-grounded evaluation set. No inference or app writes."""
import hashlib
import html
import json
import sys
from collections import Counter
from pathlib import Path
import psycopg

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from study_desk.config import DATABASE
CATEGORIES = ['Lecture details', 'Understanding', 'Application', 'Connections']
questions, answers = [], []

def add(lecture, category, question, checklist, evidence, note=''):
    category = CATEGORIES[category - 1]
    number = 1 + sum(q['lecture_id'] == lecture and q['category'] == category for q in questions)
    qid = f'L{lecture:02}-{CATEGORIES.index(category)+1}-{number}'
    questions.append(dict(id=qid, lecture_id=lecture, category=category, question=question))
    origin = 'new worked scenario' if category == 'Application' else 'cross-lecture synthesis' if category == 'Connections' else 'transcript-grounded explanation'
    answers.append(dict(id=qid, expected_answer_checklist=checklist, evidence_ids=evidence.split(), answer_origin=origin, grading_note=note))

# Reviewed source windows, in minutes. The renderer preserves exact caption text,
# segment indices and timestamps, rather than treating generated guides as sources.
WINDOWS = {
 1: {'knowledge':(18,22), 'machine':(25,29), 'semantics':(39,44), 'types':(45,49), 'operators':(49,53.5)},
 2: {'scope':(2,4), 'river':(7,11.3), 'generator':(11.3,14), 'names':(14,17), 'perception':(29,32.8)},
 3: {'queue':(14,21), 'extended':(22,24), 'hill':(26,28), 'beam':(31,36), 'terrain':(37,41)},
 4: {'oracle':(6,10.5), 'stop':(14,18), 'extended':(20,25), 'heuristic':(25,33), 'consistency':(43,48)},
 5: {'static':(3,8), 'minimax':(17,21), 'pruning':(22,28), 'work':(32,35), 'deepening':(35,43)},
 6: {'features':(8,14), 'articles':(17,24), 'robot':(24,30), 'scaling':(38,42)},
 7: {'tests':(3,9), 'vampires':(9,15), 'entropy':(24,30), 'weighted':(32,39), 'numeric':(41,46), 'rules':(46,50)},
 8: {'objective':(16,21), 'smooth':(21,26), 'chain':(28,34), 'derivative':(37,39), 'training':(39,43), 'reuse':(45,50)},
 9: {'vision':(6,12), 'autocoder':(15,19), 'probability':(27,32.7), 'outputs':(32.7,36), 'width':(38,44), 'meaning':(45,49)},
 10:{'boundary':(4,12), 'margin':(16,22), 'weights':(27,30), 'kernel':(35,45)}
}

# QUESTIONS_START
add(1,1,"In Grimson's 2008 introduction to Python, what stopping test and update rule does the square-root recipe use?",
    ['Stop and return the guess g when g squared is sufficiently close to x.', 'Otherwise replace g with (g + x/g)/2 and repeat.'], '1:knowledge')
add(1,1,"In the 2008 Python introduction, how does Grimson distinguish the string '52' from the number 52?",
    ['Quotes mark a sequence of characters as a string; 52 without quotes is a number.', 'Their types determine which operations apply and what those operations mean.'], '1:types')
add(1,1,"In Grimson's stored-program computer explanation, what does the program counter point to, and how can a test change execution?",
    ['It points to the location of an instruction in memory.', 'Execution normally advances to the next instruction; a test can change the counter to another instruction location.'], '1:machine')
add(1,2,"Why does a definition of a square root not, by itself, provide a procedure for computing one? Explain using declarative and imperative knowledge.",
    ['Declarative knowledge states what is true and can let us check a proposed answer.', 'Imperative knowledge specifies executable steps, tests and a stopping condition for finding the answer.'], '1:knowledge')
add(1,2,"Why can a program pass a syntax check and still give the wrong answer? Use Grimson's distinction between syntax and semantics.",
    ['Legal expression structure is different from meaningful operations and intended behavior.', 'A program can run with valid syntax and still perform the wrong computation; syntax checking does not establish correctness.'], '1:semantics')
add(1,2,"Why does Python allow '3' * 3 but reject '3' * '3', according to the operator discussion in the introductory lecture?",
    ['String times integer means repetition, producing the string 333 in the first case.', 'Two strings do not have a supported multiplication operation; operand types control the meaning and validity of the operator.'], '1:operators')
add(1,3,"Use the lecture's square-root recipe with x = 9 and g = 2. Stop only when |g*g - x| < 0.01. Should it stop now, and what is the next guess?",
    ['The current squared error is |4 - 9| = 5, so the stopping test fails.', 'The next guess is (2 + 9/2)/2 = 3.25.'], '1:knowledge')
add(1,3,"Consider these expressions separately: '52' + '7', 52 + 7, and '52' * '7'. What does each produce or why does it fail?",
    ["The first concatenates strings to give '527'; the second adds numbers to give 59.", 'The third fails because multiplication is not defined between two strings.'], '1:types 1:operators')
add(1,3,"Use the Python 2-style integer division demonstrated in the 2008 lecture, with no future-division import: what are 7 / 2 and 7 / 2.0, and why do they differ?",
    ['7 / 2 gives the integer 3 under the specified historical division behavior.', '7 / 2.0 gives 3.5 because a floating-point operand requests real division.'], '1:operators',
    'The version is intentional. Do not apply Python 3 true division to the first expression; naming that distinction is welcome but not required.')
add(1,4,"Connect Grimson's idea of an executable recipe with Winston's farmer–fox–goose–grain state graph. Why does representing the legal states still leave an algorithmic task to perform?",
    ['The state graph describes situations, allowed transitions and constraints.', 'An algorithm must still specify how to explore transitions, choose the next step and recognize the goal; that is the imperative recipe.'], '1:knowledge 2:river')
add(1,4,"How does the queue-based depth-first search procedure illustrate the sequence, tests and changing control flow described in the introductory programming lecture?",
    ['Search initializes a queue, tests a path, expands it when needed and repeats.', 'The goal/dead-end tests and queue updates determine what happens next, illustrating controlled execution rather than a bare statement of the desired answer.'], '1:machine 3:queue')
add(1,4,"Relate the Python lecture's emphasis on data representation to the nearest-neighbor lecture's magazine example. Why can a valid numeric representation still lead to an unhelpful comparison?",
    ['A representation determines the operations available but does not automatically make those operations appropriate for the task.', 'Raw word-count vectors are numeric, yet Euclidean distance can favor short documents; comparing vector direction addresses the length mismatch.'], '1:types 6:articles',
    'This is a synthesis of the two examples, not a claim that the Python lecture discusses document retrieval.')

add(2,1,"In Winston's Introduction and Scope lecture, which three activities does his broad definition of artificial intelligence target?",
    ['Thinking, perception and action.', 'He frames AI in terms of models of these activities, supported by representations, constraints and algorithms.'], '2:scope 2:river')
add(2,1,"Which everyday identification example does Winston use to introduce generate-and-test, and what plays the role of the generator?",
    ['He identifies a tree leaf using a field guide to North American trees.', 'Turning through possible tree descriptions generates candidates; comparing them with the leaf tests the candidates.'], '2:generator')
add(2,1,"For the farmer, fox, goose and grain example, how many bank assignments exist before constraints are applied, and why are some missing from the legal-state graph?",
    ['Four entities with two possible banks give 2^4 = 16 assignments.', 'Unsafe assignments in which something gets eaten are excluded.'], '2:river')
add(2,2,"What does Winston mean by the Rumpelstiltskin Principle, and why does giving generate-and-test a name help?",
    ['Naming an idea makes it possible to refer to it, discuss it and attach knowledge to it.', 'Once the method has a name, we can discuss useful properties such as avoiding duplicate candidates and using information to narrow generation.'], '2:generator 2:names')
add(2,2,"Why is a state graph a more useful representation of the river-crossing puzzle than a picture of the farmer alone?",
    ['It explicitly records participant locations and possible moves.', 'It exposes safety constraints and routes between the initial and goal situations, enabling a search procedure.'], '2:river')
add(2,2,"Why does Winston describe thinking and perception as a loop rather than completely separate abilities in the imagination demonstration?",
    ['A description triggers an imagined scene or relevant visual memory.', 'Visual processing of that scene provides information used to answer a question, so thinking invokes perception and uses its result.'], '2:perception')
add(2,3,"A river puzzle has a farmer and four independently positioned possessions, each on either bank. Before checking any safety or boat rules, how many location assignments must a complete enumeration consider? Explain the count.",
    ['There are five independently binary positions, including the farmer.', 'The count is 2^5 = 32; legality filtering can reduce this set afterward.'], '2:river')
add(2,3,"A tree-identification program repeatedly tests the same candidate and keeps proposing conifers after being told the leaf is deciduous. What two generator improvements follow from Winston's discussion?",
    ['Make generation nonredundant, avoiding repeated candidate solutions.', 'Make it informable: use the deciduous-tree information to exclude incompatible candidates.'], '2:generator')
add(2,3,"Suppose a system has a visual memory of Alice giving a ball to Bob and is asked who has the ball afterward. Describe how Winston's imagine-then-inspect approach could answer, without claiming the system must have memorized that exact question.",
    ['Use the description to retrieve or construct the relevant transfer scene.', 'Inspect the scene to determine the recipient/possession relation and answer Bob; the same scene can support more than one question.'], '2:perception',
    'The names and question are new; the mechanism is adapted from the lecture demonstration.')
add(2,4,"Winston says representations expose constraints that enable algorithms. How does the support-vector-machine lecture put that idea into practice with a separating street?",
    ['Vectors and a separating boundary turn the classification task into a geometric representation.', 'Constraints on positive/negative examples and a margin objective make it possible to optimize a decision rule.'], '2:river 10:boundary 10:margin')
add(2,4,"Compare identifying a leaf by generate-and-test with finding a relevant magazine article by nearest-neighbor comparison. What supplies the candidates and what supplies the comparison in each?",
    ['The field guide supplies candidate trees and the observed leaf supplies a match test.', 'The article library supplies candidate documents and word-count-vector similarity compares them with a query; its metric must suit the representation.'], '2:generator 6:articles')
add(2,4,"How does the power of symbolic names in Introduction and Scope relate to turning an identification tree into if-then rules?",
    ['Names make properties and concepts explicit enough to communicate and reason about.', 'A root-to-leaf path can be expressed using named tests and outcomes as rule conditions, with the leaf identification as the conclusion.'], '2:names 7:rules')

add(3,1,"In the queue implementation of search, where are new paths inserted for depth-first search, and what one change produces breadth-first search?",
    ['Depth-first search places newly extended paths at the front.', 'Breadth-first search places them at the back of the queue.'], '3:queue')
add(3,1,"In Winston's beam-search demonstration, what beam width is used and what does that width limit?",
    ['The example uses width two.', 'It keeps the two best paths at a level, judged by closeness to the goal, rather than keeping two successors for every parent independently.'], '3:beam')
add(3,1,"What three terrain problems does Winston describe for continuous hill climbing near the end of the basic-search lecture?",
    ['A local maximum and a flat plateau can prevent useful progress.', 'A narrow diagonal ridge can make all sampled cardinal directions look downhill even though an uphill direction exists.'], '3:terrain')
add(3,2,"Why does an extended list save work when different search paths reach the same node?",
    ['It records nodes whose outgoing continuations have already been explored.', 'It avoids repeatedly extending equivalent continuations reached by different paths.'], '3:extended',
    'This question concerns the basic search mechanism, not a blanket optimality guarantee for arbitrary weighted search.')
add(3,2,"In this lecture's hill-climbing search, why does preferring a successor closer to the goal not by itself establish that the complete route is shortest?",
    ['The heuristic ranks apparent distance remaining rather than all accumulated route costs.', 'A locally attractive direction need not give the best complete route; this ordering is a guide, not an optimality proof.'], '3:hill 3:beam')
add(3,2,"Why does a width-two beam differ from simply allowing two children from every expanded parent?",
    ['Beam width constrains the retained frontier across a whole level.', 'Choosing two per parent can create many more than two surviving paths and fails to impose the same global limit.'], '3:beam')
add(3,3,"The queue is [S-A, S-B]. Expanding its first path S-A produces S-A-C followed by S-A-D. There are no loops or goal nodes. What is the resulting queue for depth-first search and for breadth-first search?",
    ['DFS: [S-A-C, S-A-D, S-B].', 'BFS: [S-B, S-A-C, S-A-D].'], '3:queue')
add(3,3,"In the lecture's front-sorted hill-climbing queue, expanding S-A generates S-A-C with heuristic 7 and S-A-D with heuristic 2; S-B is already waiting. Smaller estimates are better. What queue order results, and which path is considered next?",
    ['Sort the new extensions by their heuristic and place them in front: [S-A-D, S-A-C, S-B].', 'S-A-D is next; the lecture sorts the new extensions, not the entire waiting queue.'], '3:hill 3:beam')
add(3,3,"At one level, a beam search has four candidate paths ending at A, B, C and D with estimated remaining distances 8, 3, 5 and 1. With beam width two and smaller estimates preferred, which survive? Can a discarded path still belong to the actual best solution?",
    ['D and B survive because they have the two lowest estimates.', 'Yes: heuristic ranking can discard a path that would ultimately be best; the width limit alone does not guarantee optimality.'], '3:beam')
add(3,4,"Contrast breadth-first search's level ordering with branch-and-bound's accumulated-distance ordering. Why can fewest edges and lowest route cost be different goals?",
    ['Breadth-first explores by depth/number of edges, whereas branch-and-bound orders paths by accumulated cost.', 'When edge costs differ, a route with more edges can have lower total cost; the two rankings need not agree.'], '3:queue 4:oracle 4:stop')
add(3,4,"How does the neural-net lecture adapt the continuous hill-climbing idea, and what extra information does it use instead of just trying a few directions?",
    ['Both seek improvements in an objective over a parameter space.', 'Neural-net training uses partial derivatives/the gradient to guide weight changes, with a rate constant controlling step size; local-search difficulties are not automatically eliminated.'], '3:terrain 8:objective 8:smooth')
add(3,4,"How does the extended-list idea implement the nonredundancy property recommended for generate-and-test?",
    ['Generate-and-test should avoid generating or considering the same solution repeatedly.', 'An extended list prevents repeated expansion of a node reached through multiple paths, eliminating repeated continuation work.'], '3:extended 2:generator')

add(4,1,"In the optimal-search lecture's oracle example, what route and total length does Juana supply?",
    ['The route is S-A-D-G.', 'Its total length is 11.'], '4:oracle')
add(4,1,"In the first Cambridge-map comparison in the optimal-search lecture, how does adding an extended list change the number of branch-and-bound extensions?",
    ['Extensions decrease from 835 to 38 in that example.', 'The saving comes from not expanding a node again after reaching it by a no-better route.'], '4:extended')
add(4,1,"What stronger heuristic property does Winston introduce after showing that an admissible heuristic can fail with his no-reopening extended-list implementation?",
    ['Consistency.', 'In the undirected formulation shown, the absolute difference between two heuristic estimates cannot exceed the actual distance between the nodes.'], '4:consistency')
add(4,2,"For branch-and-bound with nonnegative edge costs, why can it stop when the least-cost path removed from its queue already reaches the goal, but not necessarily when a goal path is first generated?",
    ['When the goal path is least-cost, all queued alternatives already cost at least as much and cannot improve through nonnegative extensions.', 'A newly generated goal path can coexist with cheaper unfinished paths, so discovery alone is not the same stopping condition.'], '4:oracle 4:stop')
add(4,2,"Why does adding an admissible estimate of distance remaining to accumulated route cost help guide an optimal search?",
    ['Accumulated cost is already spent; the admissible remaining estimate does not overstate the best possible cost still needed.', 'Their sum supplies a lower-bound estimate of a complete route, helping prioritize promising paths and reject paths that cannot beat an incumbent.'], '4:heuristic',
    'For graph search that permanently closes nodes, consistency or an appropriate reopening policy also matters; do not claim admissibility alone makes every implementation correct.')
add(4,2,"Why can an admissible but inconsistent heuristic cause the lecture's extended-list A* implementation to miss a shorter route?",
    ['It can cause a node to be expanded through a worse route before a better route is found.', 'The extended list then refuses the later improvement; the lecture strengthens the heuristic condition to consistency.'], '4:consistency',
    'Keep the implementation qualification: this is not a claim that all forms of A* fail with admissible inconsistent heuristics.')
add(4,3,"Three queued routes have (cost so far g, estimated remainder h) values A=(4,6), B=(7,1), C=(3,8). Which is chosen using g+h, and which using g alone?",
    ['g+h scores are A=10, B=8, C=11, so the heuristic-guided choice is B.', 'Using g alone chooses C, whose accumulated cost is 3.'], '4:oracle 4:heuristic')
add(4,3,"A complete route costs 11. Two unfinished routes have accumulated costs 12 and 11, and every remaining edge has nonnegative cost. If we need any shortest route, can both be pruned? Could the second still tie the incumbent?",
    ['Neither route can improve on 11, so both may be pruned when any one shortest route is sufficient.', 'The cost-11 route could tie if its remaining edges total zero; pruning it does not enumerate every shortest route.'], '4:oracle 4:stop')
add(4,3,"For an undirected edge X-Y of cost 2, let true remaining distances be 5 from X and 3 from Y, and estimates be h(X)=4 and h(Y)=0. Are these estimates admissible? Do they satisfy the lecture's consistency test on this edge?",
    ['Both are admissible: 4 <= 5 and 0 <= 3.', 'They are not consistent on this edge because |4-0|=4 exceeds 2.'], '4:consistency')
add(4,4,"Beam search and A* both use heuristic information. Why does their use of that information give different protection against throwing away the best route?",
    ['Beam search retains only a fixed number of apparently promising paths and can discard a winning route.', 'Properly implemented A* uses cost plus a suitable lower-bound heuristic rather than a fixed-width cutoff; its optimality relies on the relevant heuristic/graph-search conditions.'], '3:beam 4:heuristic 4:consistency')
add(4,4,"What does the dead horse principle have in common in branch-and-bound and alpha-beta pruning, and what is the bound about in each case?",
    ['Both avoid work on a branch that cannot improve the decision already available.', 'Branch-and-bound compares route-cost bounds with a goal cost; alpha-beta compares game-value bounds under alternating maximizing and minimizing choices.'], '4:oracle 4:extended 5:pruning 5:deepening')
add(4,4,"Compare the role of distance in heuristic route search with its role in nearest-neighbor classification. Why is an airline-distance estimate not interchangeable with a feature-vector similarity score?",
    ['Route search estimates remaining travel cost to a goal, with lower-bound conditions relevant to optimality.', 'Nearest-neighbor distance or similarity compares feature representations to choose a matching example; it need not be a bound on the cost of a path.'], '4:heuristic 6:features 6:articles')

add(5,1,"In the games lecture, what does a static board evaluator inspect, and which two chess features are mentioned as examples?",
    ['It evaluates the current board without exploring its future consequences.', 'King safety and pawn structure are named; features can be combined with weights in a linear scoring polynomial.'], '5:static')
add(5,1,"In Winston's small minimax example, the minimizing branches have leaves (2,7) and (1,8). What values back up to those branches, and what value reaches the maximizing root?",
    ['The minimizing branches return 2 and 1.', 'The maximizing root returns 2, choosing the first branch.'], '5:minimax')
add(5,1,"What does the games lecture call the strategy of completing shallower searches before deeper ones so a move is available when time expires?",
    ['Progressive deepening; iterative deepening is an acceptable equivalent term.', 'It is presented as an anytime approach with a completed shallower result as an insurance policy.'], '5:deepening')
add(5,2,"Why does minimax not simply choose the largest leaf value anywhere in the game tree?",
    ['The opponent controls alternate decisions and seeks to minimize the maximizing player’s value.', 'Values must be backed up using the correct min/max choice at each level; the maximizing player cannot force every attractive leaf.'], '5:minimax')
add(5,2,"Does alpha-beta pruning approximate minimax or change its backed-up value? Explain what work it can avoid.",
    ['For the same tree and leaf evaluations, it preserves the minimax value rather than approximating it.', 'It avoids evaluations and even move generation in subtrees whose bounds show they cannot change the decision.'], '5:pruning 5:deepening',
    'Tied best moves can be selected differently; do not require an identical tie-breaking choice.')
add(5,2,"Why is progressive deepening useful when a game-playing program has a fixed time limit and the branching factor varies?",
    ['It is hard to know in advance which depth can be completed within the available time.', 'A completed shallower result remains available if the next deeper search cannot finish; earlier levels are relatively inexpensive compared with the deepest level.'], '5:work 5:deepening')
add(5,3,"A MAX root has three MIN children A, B and C. Their leaf scores are A:[4,9], B:[2,8], C:[6,7]. What scores back up, and which move should MAX choose?",
    ['A returns 4, B returns 2 and C returns 6.', 'MAX chooses C with value 6.'], '5:minimax')
add(5,3,"A MAX root has already completed one MIN branch with value 5. In a second MIN branch, the first evaluated leaf is 3 and the other leaf is unknown. Can alpha-beta skip that unknown leaf, and why?",
    ['Yes: the second MIN branch can return at most 3 after seeing the first leaf.', 'The root already has 5, so this branch cannot improve its decision, regardless of the unknown leaf.'], '5:pruning')
add(5,3,"For a uniform game tree with branching factor 4 and depth 6, how many leaf evaluations does plain minimax require? Using the lecture's ideal-order approximation 2*b^(d/2), what is the alpha-beta estimate?",
    ['Plain minimax evaluates 4^6 = 4096 leaves.', 'The ideal-order approximation gives 2*4^3 = 128; this is an ideal-case estimate, not a universal observed count.'], '5:minimax 5:work')
add(5,4,"Compare the conditions for stopping a route search and stopping a depth-limited game search. How do branch-and-bound and minimax each decide that one candidate is better?",
    ['Branch-and-bound minimizes accumulated route cost and uses bounds to establish a shortest goal route.', 'Minimax uses backed-up board evaluations while accounting for an adversary; a good game move is not simply the shortest path to an attractive leaf.'], '4:stop 5:static 5:minimax')
add(5,4,"Both beam search and alpha-beta pruning discard branches. Why is it wrong to describe both as sacrificing answer quality merely to search faster?",
    ['Beam search imposes a width cutoff based on heuristic ranking and can discard the best solution.', 'Alpha-beta removes branches proven unable to change the minimax value for the same search horizon and evaluations.'], '3:beam 5:pruning 5:deepening')
add(5,4,"A minimax game tree and an identification tree are both trees. What do their internal nodes, branches and results represent, and why should their traversal rules differ?",
    ['A game tree branches on possible moves, alternates players and backs up adversarial values.', 'An identification tree branches on observed test outcomes and reaches a class label; it follows the input’s outcomes rather than optimizing against an opponent.'], '5:minimax 7:tests 7:rules')

add(6,1,"What two measurements represent electrical outlet covers in the nearest-neighbor lecture's introductory example?",
    ['Total cover area, including the hole area.', 'Hole area; the two measurements place each cover in a feature space.'], '6:features')
add(6,1,"Which magazines and example word dimensions does Winston use to illustrate document retrieval with nearest-neighbor ideas?",
    ['Wired and Town and Country.', 'Computer and hack, including variants such as hacker/hacking; hack can refer to different subject matter in the two magazines.'], '6:articles')
add(6,1,"In the robot-arm learning example, what motor outputs are recorded alongside joint positions, velocities and accelerations?",
    ['The torques on the two motors.', 'Those records associate observed motion states with the torques used to produce them.'], '6:robot')
add(6,2,"Why does comparing raw word-count vectors by Euclidean distance risk retrieving the wrong articles for a short query, and how does the lecture address it?",
    ['The short query has small counts, so vector length can dominate distance even when subject matter differs.', 'Cosine/angle comparison emphasizes relative direction through a normalized dot product rather than raw magnitude.'], '6:articles')
add(6,2,"How does dividing each feature by its standard deviation address one nearest-neighbor problem, and what problem does it leave unresolved?",
    ['It puts feature spreads on comparable scales, giving each transformed feature unit variance.', 'It does not establish which features matter; irrelevant features can still distort the comparison.'], '6:scaling')
add(6,2,"What does the nearest-neighbor lecture's cake-without-flour warning mean for a prediction task?",
    ['The supplied measurements may lack information about the target.', 'A learning procedure cannot reliably recover a relationship that the available features do not contain; feature relevance must be checked.'], '6:scaling')
add(6,3,"A one-nearest-neighbor classifier uses Euclidean distance. Its only stored examples are A at (0,0) and B at (4,0). What label does query (3,1) receive? Show the two distances.",
    ['Distances are sqrt(10) to A and sqrt(2) to B.', 'The classifier chooses B.'], '6:features')
add(6,3,"For word-count vectors q=(1,1), A=(10,10) and B=(1,0), which article wins under Euclidean distance and which under cosine similarity? Explain the disagreement.",
    ['Euclidean distance selects B: distances are sqrt(162) to A and 1 to B.', 'Cosine selects A: similarities are 1 and 1/sqrt(2), respectively; A shares the query’s direction despite its larger magnitude.'], '6:articles')
add(6,3,"Two examples differ by 200 units on feature x and 2 units on feature y. Training-set standard deviations are sigma_x=100 and sigma_y=1. After the lecture's scaling, what are the differences and Euclidean distance? What changes about their relative contributions?",
    ['Scaled differences are 2 and 2; the distance is sqrt(8).', 'The dimensions now contribute equally to squared distance, whereas raw units let x dominate.'], '6:scaling')
add(6,4,"Why is the identification-tree approach a useful alternative to the nearest-neighbor setup when inputs include symbolic tests and tests have different costs?",
    ['The numerical-distance setup needs a meaningful representation/metric; symbolic outcomes do not directly supply the same geometry.', 'A test tree can branch on symbolic outcomes and avoid unnecessary or expensive tests on particular paths.'], '6:features 7:tests')
add(6,4,"Connect the robot-arm lookup example to Grimson's distinction between knowing a mathematical description and having a workable computational recipe. Why might recorded experience be useful even when equations of motion exist?",
    ['Equations describe the mechanics, but practical execution also depends on friction, wear and imperfect measurements.', 'Recording nearby motion states and motor torques supplies a procedure for choosing actions from experience rather than relying solely on an idealized analytic calculation.'], '1:knowledge 6:robot',
    'Do not claim that all mathematical equations are declarative or that analytic control is impossible; the comparison concerns the particular example.')
add(6,4,"Contrast using stored motion examples to control a robot arm with using an autocoder's small hidden layer to represent inputs. How is information reused in these two approaches?",
    ['The robot uses stored observations to find nearby motion conditions and associated torques.', 'The autocoder learns weights and a compressed hidden representation by reconstructing inputs; it does not simply look up a stored motion record.'], '6:robot 9:autocoder')

add(7,1,"What four observable characteristics are used as candidate tests in Winston's vampire identification example?",
    ['Whether a shadow is cast and whether garlic is eaten.', 'Complexion and accent.'], '7:vampires')
add(7,1,"Which test does the vampire example select first under weighted disorder, and what weighted disorder does the lecture give it?",
    ['The shadow test.', 'Its weighted disorder is 0.5, below the alternatives shown.'], '7:weighted',
    'The captions contain the stray phrase 1/5 immediately before 0.5; the stated calculation (1/2)*1 + (3/8)*0 + (1/8)*0 gives 0.5.')
add(7,1,"When the lecture converts an identification tree into rules, which part of the tree supplies one initial rule?",
    ['A path from the root to a leaf.', 'Tests/outcomes on that path become the conditions and the leaf label becomes the conclusion, initially giving one rule per leaf.'], '7:rules')
add(7,2,"Why might an identification tree use a measurement on one branch but never perform it on another?",
    ['A test can be useful only for a subset of cases after earlier outcomes are known.', 'Already homogeneous subsets need no further separation, so omitting tests can reduce cost.'], '7:tests 7:numeric')
add(7,2,"Why does the lecture weight each branch's disorder by the fraction of samples entering that branch instead of adding all branch disorders equally?",
    ['An unweighted sum treats tiny and large branches as equally influential.', 'Weighting measures the remaining disorder across the sample population, taking branch sizes into account.'], '7:weighted')
add(7,2,"For an identification tree using one numeric feature threshold at a time, why are boundaries axis-aligned, and why should a later split not automatically extend across the entire feature space?",
    ['A threshold on one coordinate creates a boundary parallel to the other coordinate axis.', 'A later test applies only to samples in its existing branch/region, not to regions already separated by earlier tests.'], '7:numeric')
add(7,3,"Using binary disorder H=-p*log2(p)-(1-p)*log2(1-p), compare a set with two positives and two negatives to a set with four positives and no negatives. What are the disorders and which is purer?",
    ['The balanced set has disorder 1 bit.', 'The pure set has disorder 0, using the limiting value 0*log2(0)=0; it is purer.'], '7:entropy')
add(7,3,"Test A splits eight examples into three branches: three positives, three negatives, and a balanced pair. Test B splits the same examples into two balanced groups of four. Calculate weighted disorder for each and choose the preferred split by the lecture's criterion.",
    ['A has (3/8)*0 + (3/8)*0 + (2/8)*1 = 0.25.', 'B has (4/8)*1 + (4/8)*1 = 1, so A is preferred because its remaining weighted disorder is lower.'], '7:entropy 7:weighted')
add(7,3,"Training examples on a single numeric feature are 1:N, 2:N, 4:P, 5:P. Following the lecture's candidate-threshold method, list the three midpoint thresholds and select the one producing pure children.",
    ['The midpoint candidates are 1.5, 3 and 4.5.', 'Threshold 3 separates both N examples from both P examples and gives zero disorder in each child.'], '7:numeric 7:entropy')
add(7,4,"Connect the Python lecture's distinction between kinds of values with the identification-tree lecture's difficulty applying its earlier numeric nearest-neighbor setup to vampire tests. What representation issue must be solved?",
    ['Values have types and meanings that constrain useful operations; a symbolic outcome is not automatically a meaningful numeric distance.', 'Tests such as shadow=yes/no/unknown can be handled directly by branches; arbitrary numeric codes would need an appropriate metric before distance-based comparison makes sense.'], '1:types 7:tests')
add(7,4,"The identification-tree lecture favors a small tree, but the deep-net demonstration trains a wide network before reducing it. Why are these positions not necessarily contradictory?",
    ['A small final representation can reduce complexity or cost.', 'Finding that representation is a separate training problem: the wider net can reach a solution that a small network trained from scratch fails to find in the demonstration.'], '7:tests 9:width',
    'The neural-net observation is about the demonstrated optimization behavior, not a theorem that wider is always better.')
add(7,4,"Why can if-then rules obtained from an identification tree be useful for classification even though the games lecture says simple board-to-move rules are not enough for strong chess play?",
    ['Identification rules map observed test outcomes to a class using a learned partition.', 'Choosing a chess move requires accounting for future consequences and an opponent; a current-board rule can omit those effects.'], '7:rules 5:static 5:minimax')

add(8,1,"In the neural-net lecture, how is a neuron's threshold represented so it can be treated as another weight?",
    ['Add a constant input of -1.', 'Give that input weight w0=t, subtracting t from the summed input and shifting the decision threshold to zero.'], '8:smooth')
add(8,1,"Which smooth activation replaces the hard step in the neural-net lecture, and what happens to its output at very large positive and negative inputs?",
    ['The logistic sigmoid, 1/(1+exp(-a)).', 'It approaches 1 for very large positive a and 0 for very large negative a.'], '8:smooth')
add(8,1,"In the small-network training demonstration, what happens when the rate constant is raised from 0.5 to 5 and then to 50?",
    ['The increase to 5 produces much faster convergence in the shown trials.', 'At 50 the trials worsen and show instability; increasing the step size is not always beneficial.'], '8:training')
add(8,2,"Why does Winston put a minus sign on the squared-error performance function, and does this change what counts as a perfect prediction?",
    ['He wants improvement to mean going uphill/maximizing rather than minimizing.', 'Zero error remains the optimum; maximizing negative squared error and minimizing squared error seek the same fit.'], '8:objective')
add(8,2,"Why is a hard step activation inconvenient for the gradient-based training procedure introduced in the lecture?",
    ['Its discontinuity and flat regions do not provide the smooth, useful derivatives needed for the proposed updates.', 'A sigmoid supplies a differentiable transition that allows weight effects to be propagated through the network.'], '8:smooth')
add(8,2,"Why does backpropagation not need to separately recompute every possible path through a multilayer network?",
    ['Chain-rule expressions share downstream partial results.', 'Reusing those results across connections avoids the apparent exponential path enumeration; work follows the connections and layers instead.'], '8:chain 8:reuse')
add(8,3,"For the lecture's sigmoid s(a)=1/(1+exp(-a)), what are s(0) and its derivative at a=0? Use the derivative form expressed in terms of the output.",
    ['s(0)=1/2.', 's prime = s*(1-s), so s prime at 0 is 1/4.'], '8:smooth 8:derivative')
add(8,3,"A weight is w=2, the derivative of the performance to be maximized is dP/dw=-0.4, and the rate constant is 0.1. Using gradient ascent, what is the updated weight? Does one such step prove a global optimum has been found?",
    ['w_new = 2 + 0.1*(-0.4) = 1.96.', 'No; a local gradient update does not establish global optimality.'], '8:objective 8:smooth')
add(8,3,"A small network has a single dependency chain w -> h -> z -> P. At the current point, dh/dw=2, dz/dh=0.3 and dP/dz=-4. What is dP/dw, and which local derivatives are combined?",
    ['Multiply along the chain: (-4)*0.3*2 = -2.4.', 'The result combines the performance-to-output, output-to-hidden, and hidden-to-weight derivatives.'], '8:chain')
add(8,4,"How are the neural-net lecture's rate constant and the basic-search lecture's continuous hill climbing connected? Why can an oversized step undermine a locally promising direction?",
    ['Both move through a landscape seeking a better objective value; the gradient refines the choice of direction.', 'The rate constant controls travel distance, and a large step can jump past a better region or across a hill rather than improve performance.'], '3:terrain 8:objective 8:training')
add(8,4,"Winston compares backpropagation's reuse principle with an extended list in search. What repeated work is avoided in each case, and what is being reused?",
    ['Search remembers already-expanded nodes to avoid re-expanding their continuations.', 'Backpropagation reuses computed downstream derivative contributions across weights instead of deriving every full path independently.'], '3:extended 8:reuse')
add(8,4,"How does the deep-net lecture's probabilistic output training differ from the earlier negative-squared-error example, and what optimization idea do they share?",
    ['The earlier example optimizes agreement between desired and actual outputs via squared error; the later example fits class probabilities to observed labeled samples.', 'Both adjust parameters using derivatives to improve a chosen performance objective.'], '8:objective 9:probability')

add(9,1,"Which three animals are used in the deep-neural-net classroom demonstration, and what observation is used to distinguish them?",
    ['Cheetah, zebra and giraffe.', 'Their shadow heights supply the input information.'], '9:autocoder 9:width')
add(9,1,"In the deep-net lecture's convolution illustration, what approximate image and local-window sizes are given, and what operation follows to select local maxima?",
    ['The illustration uses an image about 256 by 256 and a local window about 10 by 10.', 'Max pooling takes maxima over local neighborhoods of the resulting activations.'], '9:vision',
    'These are the lecture’s illustrative dimensions, not universal CNN requirements.')
add(9,1,"In the deep-net width demonstration, how does gradually removing neurons after training compare with starting training with only two neurons per column?",
    ['The trained network can be reduced and retrained down to two per column while retaining a solution.', 'Starting the narrow network from scratch fails to find the solution in the shown demonstration, getting trapped in poor optimization behavior.'], '9:width')
add(9,2,"Why can an autocoder learn something useful even though its desired output is just its input?",
    ['A smaller hidden layer forces the data through a bottleneck.', 'Successful reconstruction requires a useful compact representation of regularities rather than an unrestricted identity copy.'], '9:autocoder',
    'This describes the lecture’s bottleneck model; do not assume every autoencoder automatically learns meaningful generalization.')
add(9,2,"Why can the same image classifier have a lower top-five error than top-one error? Explain what each measure accepts as a correct result.",
    ['Top-one requires the correct label to rank first.', 'Top-five also accepts it at ranks two through five, so a top-one mistake can still be a top-five success.'], '9:vision')
add(9,2,"Why does Winston caution against inferring human-like understanding from plausible image labels and captions?",
    ['A system can respond to local visual evidence or texture and still label/caption an image convincingly.', 'Errors and unfamiliar-looking images that retain the same predicted class show that successful labels do not establish the same perception or understanding as a person.'], '9:meaning')
add(9,3,"A max-pooling window contains activations [[1,4],[3,2]]. What single value does it return, and what information about the four inputs is not preserved by that value alone?",
    ['It returns 4.', 'That value alone does not preserve the other activations or their arrangement within the window.'], '9:vision')
add(9,3,"An image's true label ranks fourth in a classifier's ordered list of ten predictions. Is this a top-one success or a top-five success? What if the true label ranks sixth?",
    ['Rank four is a top-one failure but a top-five success.', 'Rank six is a failure under both criteria.'], '9:vision')
add(9,3,"A binary classifier assigns positive-class probability 0.8 to a positive example and 0.3 to a negative example. Assuming independent examples, what probability does it assign to each observed label, and what is their joint likelihood?",
    ['The positive example contributes 0.8; the negative example contributes 1-0.3=0.7.', 'Under the stated independence assumption, their product is 0.56.'], '9:probability',
    'The independence assumption and numbers are supplied for this new exercise; the transcript motivates the per-label probabilities.')
add(9,4,"If an autocoder's hidden vectors were used for nearest-neighbor retrieval, what would change compared with using raw word counts? What choice from the nearest-neighbor lecture would still matter?",
    ['The compared features would be learned compressed representations rather than fixed raw word counts.', 'The distance/similarity measure and feature scaling still matter; a learned representation alone does not guarantee relevant neighbors.'], '9:autocoder 6:articles 6:scaling',
    'This proposes a combination of the lecture ideas, not a system claimed to have been demonstrated.')
add(9,4,"Does the deep-net demonstration's success after widening provide the same kind of assurance as the SVM lecture's convex-optimization argument? Explain the difference.",
    ['The network demonstration shows a useful empirical change in optimization behavior, not a general guarantee of a global solution.', 'The SVM discussion relies on the convex structure of its standard optimization problem to rule out suboptimal local optima.'], '9:width 10:kernel',
    'Distinguish optimization guarantees from test-set accuracy or guaranteed feasibility of a hard-margin problem.')
add(9,4,"How does the broad thinking–perception–action definition in Introduction and Scope help explain the later warning that a convincing image caption is not enough to establish general intelligence?",
    ['The broad view includes models of thinking, perception and action and their interactions.', 'A successful labeling/captioning output demonstrates a narrower capability; it does not by itself show the wider understanding or interconnected abilities.'], '2:scope 2:perception 9:meaning')

add(10,1,"In the SVM lecture's street picture, how is w oriented relative to the separating boundary, and how is w used to classify a new vector u?",
    ['w is perpendicular to the boundary.', 'The decision checks the sign of w dot u + b; the lecture assigns a nonnegative result to the positive side.'], '10:boundary')
add(10,1,"When Winston derives w as a weighted sum of training vectors, what does an alpha coefficient of zero mean for that vector's contribution?",
    ['In w = sum_i alpha_i*y_i*x_i, a zero alpha contributes nothing to w.', 'Only samples with nonzero coefficients contribute to this representation of the decision boundary.'], '10:weights')
add(10,1,"Which recurring operation in both the SVM optimization and its decision rule makes the kernel substitution possible?",
    ['Dot products between sample vectors, and between a sample and an unknown vector.', 'A kernel supplies the corresponding dot products in a transformed feature space without requiring that transformation to be explicitly constructed.'], '10:kernel')
add(10,2,"Under the lecture's constraints w dot x + b >= 1 for positives and <= -1 for negatives, why does minimizing the norm of w widen the separating street?",
    ['The full street width is 2/||w|| under that scaling.', 'Reducing the norm increases the width while the classification constraints must remain satisfied.'], '10:boundary 10:margin')
add(10,2,"Why is failure to separate nonlinearly arranged classes with a straight boundary different from getting stuck at a bad local optimum?",
    ['A linear hard-margin boundary may not exist for those data in the current representation.', 'That is a feasibility/representation limitation; the standard convex optimization property does not make impossible linear separation possible.'], '10:kernel')
add(10,2,"What does the kernel trick let an SVM compute without explicitly building every transformed feature, and why does the derivation depend on dot products?",
    ['It evaluates inner products phi(x) dot phi(z) through a kernel K(x,z).', 'Because the optimization and prediction formulas depend on those products, they can operate through K instead of explicit transformed vectors.'], '10:kernel')
add(10,3,"Use the decision rule positive when w dot u + b >= 0, with w=(2,-1) and b=-1. Classify u=(2,1) and v=(0,2), showing their scores.",
    ['u has score 4-1-1=2, so it is positive.', 'v has score 0-2-1=-3, so it is negative.'], '10:boundary')
add(10,3,"Two separators satisfy the same +/-1 training constraints. One has ||w||=5 and the other ||w||=2. What are their full street widths, and which is preferred by the maximum-margin objective?",
    ['Their widths are 2/5=0.4 and 2/2=1.', 'The norm-2 separator is preferred because its feasible margin is wider.'], '10:margin')
add(10,3,"For the kernel K(u,v)=(u dot v + 1)^2, with u=(1,2) and v=(2,0), calculate K. Must you explicitly construct phi(u) and phi(v) to obtain this value?",
    ['u dot v = 2, giving K=(2+1)^2=9.', 'No; the kernel directly supplies the transformed-space inner product.'], '10:kernel',
    'This is a polynomial kernel example. The captions call the powered expression linear; do not require that erroneous label.')
add(10,4,"How do the nearest-neighbor lecture and the SVM lecture use dot products for different purposes? Explain why a cosine similarity score is not itself the SVM decision rule.",
    ['Nearest-neighbor document retrieval normalizes a dot product by vector norms to compare directions.', 'The SVM uses weighted sample/query inner products plus an offset to determine the side of a learned boundary; sharing an operation does not make the algorithms identical.'], '6:articles 10:boundary 10:kernel')
add(10,4,"Contrast the boundary geometry of the identification tree's single-feature threshold tests with a linear SVM on two numeric features. Could they partition the same data differently?",
    ['Single-feature tree splits create axis-aligned boundaries that apply within the relevant branch regions.', 'A linear SVM boundary is determined by its weight vector and can be oblique; its maximum-margin partition need not match the tree.'], '7:numeric 10:boundary')
add(10,4,"Both a basic neuron and a linear SVM start with a weighted combination of inputs. What distinguishes the training objective and output interpretation in the neural-net and SVM lectures?",
    ['The sigmoid network adjusts weights to improve its chosen output-fit performance and passes weighted sums through a smooth activation.', 'The SVM seeks a widest feasible separating margin and classifies by a signed decision score; that score is not automatically a calibrated probability.'], '8:objective 8:smooth 10:boundary 10:margin')


def stamp(seconds):
    return f'{int(seconds)//60:02}:{int(seconds)%60:02}'


def generate():
    presets = json.loads((ROOT / 'lecture-presets.json').read_text(encoding='utf-8'))
    lectures, evidence = [], {}
    # Read current saved-transcript selection only. Do not initialize app schemas.
    with psycopg.connect(DATABASE) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        saved = {url: (vid, path, method) for vid, url, path, method in connection.execute(
            'SELECT v.id,v.url,p.transcript_path,p.method FROM video_intake v JOIN video_processing p ON p.video_id=v.id')}
    for n, preset in enumerate(presets, 1):
        vid, path, method = saved[preset['url']]
        text_path = Path(path)
        segments_path = text_path.with_name('transcript.segments.json')
        segments = json.loads(segments_path.read_text(encoding='utf-8'))['segments']
        lecture = dict(id=n, video_id=vid, **preset, transcript_method=method,
            transcript_file=text_path.relative_to(ROOT).as_posix(),
            transcript_sha256=hashlib.sha256(text_path.read_bytes()).hexdigest(),
            segments_file=segments_path.relative_to(ROOT).as_posix(),
            segments_sha256=hashlib.sha256(segments_path.read_bytes()).hexdigest())
        lectures.append(lecture)
        for name, (a,b) in WINDOWS[n].items():
            selected = [(i,s) for i,s in enumerate(segments) if a*60 <= s['start'] < b*60]
            assert selected, (n,name)
            first, last = selected[0], selected[-1]
            eid = f'{n}:{name}'
            evidence[eid] = dict(id=eid, lecture_id=n, start_seconds=first[1]['start'],
                end_seconds=last[1]['end'], segment_indices_zero_based=[i for i,_ in selected],
                video_url=preset['url'] + '&t=' + str(int(first[1]['start'])),
                segments=[s for _,s in selected])

    assert len(questions) == len(answers) == 120
    assert len({q['id'] for q in questions}) == len({q['question'] for q in questions}) == 120
    assert Counter((q['lecture_id'],q['category']) for q in questions) == Counter(
        {(n,c):3 for n in range(1,11) for c in CATEGORIES})
    for q,a in zip(questions, answers):
        assert q['id'] == a['id'] and len(a['expected_answer_checklist']) >= 2
        ids = {evidence[e]['lecture_id'] for e in a['evidence_ids']}
        assert q['lecture_id'] in ids
        if q['category'] == 'Connections':
            assert len(ids) >= 2
    assert all(x['transcript_method'] == 'manual captions' for x in lectures)
    previous = OUT / 'sources.json'
    if previous.exists():
        old = json.loads(previous.read_text(encoding='utf-8'))
        assert [(x['transcript_sha256'],x['segments_sha256']) for x in old['lectures']] == [
            (x['transcript_sha256'],x['segments_sha256']) for x in lectures], 'Sources changed: create a new bank version instead.'

    metadata = dict(version='1.0', created_date='2026-10-28',
        description='120 questions: 10 MIT lectures x 4 categories x 3 questions. Separate from the application.',
        categories=CATEGORIES, authoring='AI-assisted authoring from saved manual-caption transcripts; no generated guides or graph outputs were used as answer sources.',
        evidence_note='Exact saved caption segments are preserved, including transcription errors. Answer checklists paraphrase clear teaching points. Numeric applications are newly constructed and explicitly supplied in the questions. Cross-lecture answers are syntheses, not quotations.',
        license_note='Adapted from MIT OpenCourseWare materials. Source license/attribution below is copied from the project’s curated lecture records. This question set and adaptations are shared under CC BY-NC-SA 4.0. No MIT endorsement is implied.',
        lectures=lectures, evidence=list(evidence.values()))
    write_json('questions.json', dict(version='1.0', questions=questions))
    write_json('answer-key.json', dict(version='1.0', answers=answers))
    write_json('sources.json', metadata)
    render('questions.html', lectures, evidence, with_answers=False)
    render('answer-key.html', lectures, evidence, with_answers=True)
    (OUT / 'README.txt').write_text(
        'STUDY DESK LITE — QUESTION BANK v1\n\n'
        '120 questions: 3 per category per lecture, across the 10 curated MIT lectures.\n'
        'Categories: Lecture details, Understanding, Application, Connections.\n'
        'All 30 Connections questions use at least two lectures.\n\n'
        'FILES\n'
        'questions.html: readable/printable question sheet, with no answers.\n'
        'questions.json: the 120 questions used in the recorded Q&A experiment.\n'
        'answer-key.html: questions, answer checklists, evidence and notes for the evaluator.\n'
        'answer-key.json: evaluator checklists and evidence IDs.\n'
        'sources.json: attribution, exact saved-caption evidence, source paths and SHA-256 hashes.\n'
        'build_bank.py: source for the authored set and offline renderer; reads the database only.\n'
        'validation.json: structural and arithmetic checks performed on this set.\n\n'
        'USE\n'
        'The recorded experiment used model-only, RAG, graph-only, and RAG + graph modes.\n'
        'Do not supply the answer key, evidence excerpts or evaluator notes to the answering model,\n'
        'and do not add this folder to the retrieval index. Retrieval should use the lecture corpus.\n'
        'Use the same question wording and comparable answering settings for all modes.\n'
        'Lecture-specific questions identify their context in the wording; no lecture UI selection is needed.\n'
        'The primary lecture groups questions for reporting; it does not restrict retrieval.\n'
        'Use the checklist as required content, not an exact-string answer. Accept equivalent explanations.\n'
        'For application questions, check the computation as well as the explanation.\n'
        'For Connections questions, look for both sides of the comparison and an explicit relationship.\n'
        'Judge factual correctness separately from whether available-source citations support the answer.\n'
        'A model without retrieval should not fabricate transcript citations.\n\n'
        'SCOPE\n'
        'This is a draft evaluation bank, not an independently expert-validated benchmark.\n'
        'Questions were based on saved manual-caption transcripts, not model-generated guides.\n'
        'Application values/scenarios are new; their underlying methods come from the cited passages.\n'
        'Connection questions test synthesis but do not assume the graph will outperform RAG.\n'
        'Some questions can be answered from general knowledge; lecture details also test source-specific recall.\n'
        'The set does not separately test unanswerable questions or refusal behavior.\n'
        'Historical Python division is explicitly scoped to the 2008 lecture’s Python 2 behavior.\n'
        'Caption formula slips are retained in evidence, not silently rewritten as source text.\n'
        'No slides, hidden diagrams, external pages or guide outputs were used as the answer key.\n'
        'The bank builder itself performs no inference. The separate Q&A runner later used\nthese questions for 1,920 recorded attempts; see ../README.md.\n\n'
        'ATTRIBUTION\n'
        'MIT OpenCourseWare. 6.00: Eric Grimson and John Guttag. 6.034: Patrick Henry Winston.\n'
        'Lecture links, titles and saved license records are in sources.json and both HTML files.\n'
        'Adaptations: original questions, worked scenarios, paraphrased checklists and cross-lecture comparisons.\n'
        'CC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/\n', encoding='utf-8')
    print('Created 120 questions, 120 answer checklists,', len(evidence), 'source windows; 30 cross-lecture questions.')


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def render(name, lectures, evidence, with_answers):
    esc = html.escape
    title = 'Answer key & evidence' if with_answers else 'Lecture question bank'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{title} — Study Desk Lite</title>',
        '''<style>
        body{font:16px/1.6 system-ui,sans-serif;margin:0;background:#f5f4ef;color:#132e4b}
        main{max-width:960px;margin:32px auto;padding:0 24px}h1{font-size:32px;line-height:1.2}h2{font-size:23px;line-height:1.3}
        h3{font-size:17px;border-bottom:2px solid #afd2e7;padding-bottom:8px;margin-top:30px}
        section{background:#fff;padding:28px;margin:24px 0;border:1px solid #d1dbe0;border-radius:10px}
        article{padding:14px 0;border-bottom:1px solid #e6eaed}article:last-child{border:0}
        .id{font:12px monospace;color:#52687b}p{margin:8px 0}a{color:#125d8c}nav{display:grid;gap:5px}
        details{margin:12px 0;background:#f3f7fa;padding:10px 14px}summary{cursor:pointer;font-weight:600}
        .note,.source{font-size:13px;color:#435e72}.question{white-space:pre-wrap}li{margin:5px 0}
        .evidence{font-size:14px;max-height:380px;overflow:auto}blockquote{margin:12px 0;border-left:3px solid #8dbdd8;padding-left:14px}
        @media print{body{background:white;color:black}main{margin:0;max-width:none}section{border:0;break-before:page;padding:0}article{break-inside:avoid}nav{display:none}.evidence{max-height:none;overflow:visible}}
        </style><main>''', f'<h1>{title}</h1>',
        '<p>10 lectures · 4 categories · 3 questions per category · 120 questions</p>',
        '<p class="note">Standalone evaluation set. The numbered lecture groups organize the questions; no lecture selection is needed to ask them.</p>']
    if with_answers:
        parts.append('<p class="note">Evaluator copy: keep out of model prompts and retrieval indexes. Checklist wording is not an exact-match requirement. Open the evidence sections for saved captions; captions can contain errors.</p>')
    parts.append('<nav>'+''.join(f'<a href="#lecture-{l["id"]}">{esc(l["title"])}</a>' for l in lectures)+'</nav>')
    amap = {a['id']:a for a in answers}
    for lecture in lectures:
        n=lecture['id']
        parts += [f'<section id="lecture-{n}"><h2>{esc(lecture["title"])}</h2>',
            f'<p class="source">{esc(lecture["creators"])} · MIT OpenCourseWare · <a href="{esc(lecture["url"])}">Video</a> · <a href="{esc(lecture["source"])}">Course source</a> · <a href="{esc(lecture["license_url"])}">{esc(lecture["license_name"])}</a></p>']
        for category in CATEGORIES:
            parts.append(f'<h3>{esc(category)}</h3>')
            for q in questions:
                if q['lecture_id'] != n or q['category'] != category: continue
                a=amap[q['id']]
                parts.append(f'<article id="{q["id"]}"><span class="id">{q["id"]}</span><p class="question">{esc(q["question"])}</p>')
                if with_answers:
                    parts.append('<ul>'+''.join('<li>'+esc(x)+'</li>' for x in a['expected_answer_checklist'])+'</ul>')
                    if a['grading_note']:parts.append('<p class="note">'+esc(a['grading_note'])+'</p>')
                    parts.append('<details><summary>Transcript evidence</summary>')
                    for eid in a['evidence_ids']:
                        e=evidence[eid]; src=lectures[e['lecture_id']-1]
                        text=' '.join(s['text'].replace('\n',' ') for s in e['segments'])
                        parts.append(f'<p class="source"><a href="{esc(e["video_url"])}">{esc(src["title"])} · {stamp(e["start_seconds"])}–{stamp(e["end_seconds"])}</a> · {esc(eid)}</p><blockquote class="evidence">{esc(text)}</blockquote>')
                    parts.append('</details>')
                parts.append('</article>')
        parts.append('</section>')
    parts.append('<p class="note">AI-assisted adaptation from the saved MIT OpenCourseWare transcripts. New questions and worked scenarios; original captions remain intact in the evidence. Adaptations shared under CC BY-NC-SA 4.0. No MIT endorsement implied. Version 1.0 · October 28, 2026.</p></main></html>')
    (OUT/name).write_text('\n'.join(parts),encoding='utf-8')


if __name__ == '__main__':
    generate()
