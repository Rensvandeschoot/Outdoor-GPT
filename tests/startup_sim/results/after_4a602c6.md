# Start-up simulation, scripts at 4a602c6

159 runs, 2026-11-08. "ready" is sim seconds from the start of custom.sh to the first green LED with the microphone open (add ~5 s for the kernel).

| id | scenario | runs | ready (s) | mode / dial at the end | findings (runs) |
|---|---|---|---|---|---|
| A1 | start in position 1 (Outdoor Tips) | 3 | 33-34 | TIPS/pos1 | ok |
| A2 | start in position 2 (Campfire Recipes), order a recipe | 3 | 34-36 | RECIPE/pos2 | ok |
| A3 | start in position 3 (Survive the Night) | 3 | 32-36 | SURVIVE/pos3 | ok |
| A4 | dial between two positions at power-up | 3 | 32-35 | SURVIVE/None, TIPS/None | RANDOM_PROMPT (3/3) |
| A5 | position 3, but its wire (GPIO17) is loose | 3 | 31-36 | TIPS/pos3, RECIPE/pos3, SURVIVE/pos3 | DIAL_MISMATCH (2/3), RANDOM_PROMPT (3/3) |
| B1 | turn 1->3 during the imports (t=4s) | 3 | 32-36 | SURVIVE/pos3 | DIAL_EVENT_LOST (3/3) |
| B2 | turn 1->3 while speech recognition loads (t=12s) | 3 | 32-35 | SURVIVE/pos3 | DIAL_EVENT_LOST (3/3) |
| B3 | turn 1->3 during the warm-up (t=22s) | 3 | 31-36 | SURVIVE/pos3 | DIAL_EVENT_LOST (3/3) |
| B4 | turn 1->3 just before ready (t=26.5s) | 3 | 33-36 | SURVIVE/pos3 | DIAL_EVENT_LOST (2/3) |
| B5 | turn 1->3 during the start message | 3 | 36-40 | SURVIVE/pos3 | ok |
| B6 | sweep 1->2->3 during start-up | 3 | 32-36 | SURVIVE/pos3 | DIAL_EVENT_LOST (3/3) |
| B7 | start in recipes (2), turn to 1 during start-up | 3 | 30-35 | TIPS/pos1 | DIAL_EVENT_LOST (3/3) |
| B8 | during start-up 1->3 and back to 1 | 3 | 30-34 | TIPS/pos1 | DIAL_EVENT_LOST (3/3) |
| B9 | during start-up 1->2 (recipes), then order a recipe | 3 | 32-35 | RECIPE/pos2 | DIAL_EVENT_LOST (3/3) |
| C1 | turn 1->3 while it listens (quiet) | 3 | 31-34 | SURVIVE/pos3 | ok |
| C2 | turn 1->3 while you talk | 3 | 30-34 | SURVIVE/pos3 | ok |
| C3 | turn 1->3 while it thinks (blue) | 3 | 30-34 | SURVIVE/pos3 | ok |
| C4 | turn 1->2 (recipes) while it thinks (blue) | 3 | 30-35 | RECIPE/pos2 | ok |
| C5 | turn 1->3 while it answers (orange) | 3 | 30-35 | SURVIVE/pos3 | ok |
| C6 | recipe being written, then turn to 1 | 3 | 31-35 | TIPS/pos1 | ok |
| C7 | two quick turns (1->2, 2 s later ->3) | 3 | 30-34 | SURVIVE/pos3 | ok |
| C8 | turn 1->3 with contact bounce | 3 | 30-35 | SURVIVE/pos3 | ok |
| D1 | short press during start-up (t=10s) | 3 | 30-35 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (3/3) |
| D2 | long press (3 s) during start-up (t=12s) | 3 | 30-34 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (3/3), LONG_PRESS_NO_EFFECT (3/3) |
| D3 | press during the start message | 3 | 35-39 | TIPS/pos1 | ok |
| D4 | press while it thinks (blue) | 3 | 30-34 | TIPS/pos1 | BUTTON_IGNORED_THINKING (3/3) |
| D5 | press while it answers (orange) | 3 | 30-35 | TIPS/pos1 | ok |
| D6 | long press (2.5 s) while it answers | 3 | 31-34 | TIPS/pos1 | LONG_PRESS_NO_EFFECT (3/3) |
| D7 | recipe done (purple), press for a new one | 3 | 31-36 | RECIPE/pos2 | ok |
| D8 | press during "give me a moment" | 3 | 31-36 | RECIPE/pos2 | GREEN_BUT_DEAF (1/3) |
| D8b | press while the recipe is being written (blue) | 3 | 32-36 | RECIPE/pos2 | BUTTON_IGNORED_THINKING (3/3) |
| D9 | press during "I heard ... is that right?" | 3 | 31-36 | RECIPE/pos2 | ok |
| D10 | short press while it listens | 3 | 30-35 | TIPS/pos1 | GREEN_BUT_DEAF (3/3) |
| D11 | long press (3 s) while it listens ("reset") | 3 | 30-34 | TIPS/pos1 | LONG_PRESS_NO_EFFECT (3/3) |
| E1 | slow cold start: chat model loads in 40 s (crank, 1.5 GHz) | 3 | 47-56 | TIPS/pos1 | ok |
| E2 | very slow start: chat model loads in 55 s | 3 | 60-60 | TIPS/pos1, None/pos1 | AGENT_EXIT (2/3) |
| E3 | chat server never starts (model missing) | 3 | - | None/pos1 | AGENT_EXIT (3/3) |
| E4 | embedding server never starts | 3 | - | None/pos1 | AGENT_EXIT (3/3) |
| E5 | warm restart (systemctl restart): model from page cache, 8 s | 3 | 30-31 | TIPS/pos1 | ok |
| E6 | chat server dies in the middle of an answer | 3 | 30-34 | TIPS/pos1 | AGENT_EXIT (3/3) |
| E7 | long conversation: 40 questions in Outdoor Tips | 1 | 31-31 | TIPS/pos1 | ok |
| E8 | a question containing "please quite" | 3 | 30-34 | TIPS/pos1 | ok |
| E9 | one request fails (server error), then ask again | 3 | 30-35 | TIPS/pos1 | ok |
| F1 | start 2, turn to 3 during start-up and press the button | 3 | 32-36 | SURVIVE/pos3 | BUTTON_LOST_AT_BOOT (3/3), DIAL_EVENT_LOST (3/3) |
| F2 | dial between positions, press during boot, turn to 1 at t=20 | 3 | 30-34 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (3/3), DIAL_EVENT_LOST (3/3), RANDOM_PROMPT (3/3) |
| F3 | start 3, press during the start message, then turn to 1 | 3 | 35-39 | TIPS/pos1 | ok |
| F4 | turn to recipes while thinking, then press to recover | 3 | 30-34 | RECIPE/pos2 | ok |
| Z01 | random combination | 1 | 39-39 | RECIPE/pos2 | ok |
| Z02 | random combination | 1 | 31-31 | RECIPE/pos2 | GREEN_BUT_DEAF (1/1) |
| Z03 | random combination | 1 | 31-31 | TIPS/pos1 | DIAL_EVENT_LOST (1/1) |
| Z04 | random combination | 1 | 33-33 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (1/1) |
| Z05 | random combination | 1 | 33-33 | RECIPE/pos2 | LONG_PRESS_NO_EFFECT (1/1) |
| Z06 | random combination | 1 | 32-32 | SURVIVE/pos3 | ok |
| Z07 | random combination | 1 | 32-32 | RECIPE/pos2 | ok |
| Z08 | random combination | 1 | 31-31 | SURVIVE/pos3 | ok |
| Z09 | random combination | 1 | 39-39 | RECIPE/pos2 | DIAL_EVENT_LOST (1/1), LONG_PRESS_NO_EFFECT (1/1) |
| Z10 | random combination | 1 | 31-31 | TIPS/pos1 | LONG_PRESS_NO_EFFECT (1/1) |
| Z11 | random combination | 1 | 33-33 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (1/1) |
| Z12 | random combination | 1 | 33-33 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (1/1) |
| Z13 | random combination | 1 | 32-32 | TIPS/pos1 | BUTTON_LOST_AT_BOOT (1/1) |
| Z14 | random combination | 1 | 32-32 | TIPS/pos1 | ok |
| Z15 | random combination | 1 | 32-32 | SURVIVE/pos3 | ok |
| Z16 | random combination | 1 | 32-32 | SURVIVE/pos3 | DIAL_EVENT_LOST (1/1), GREEN_BUT_DEAF (1/1), LONG_PRESS_NO_EFFECT (1/1) |
| Z17 | random combination | 1 | 33-33 | SURVIVE/pos3 | BUTTON_LOST_AT_BOOT (1/1), LONG_PRESS_NO_EFFECT (1/1) |
| Z18 | random combination | 1 | 38-38 | TIPS/pos1 | DIAL_EVENT_LOST (1/1) |
| Z19 | random combination | 1 | 32-32 | TIPS/pos1 | DIAL_EVENT_LOST (1/1) |
| Z20 | random combination | 1 | 33-33 | TIPS/pos1 | DIAL_EVENT_LOST (1/1), GREEN_BUT_DEAF (1/1) |

## Findings

- `AGENT_EXIT` (4 scenarios): the agent process ended; without a restart loop in the boot script the box is dead until power-cycled
- `DIAL_MISMATCH` (1 scenarios): at the end the box runs another mode than the dial points at
- `DIAL_EVENT_LOST` (16 scenarios): info: a dial edge came before its callback existed (harmless if the mode still matches)
- `BUTTON_LOST_AT_BOOT` (9 scenarios): info: a button press came before its callback existed
- `RANDOM_PROMPT` (3 scenarios): no dial position could be read, so a random mode was chosen
- `BUTTON_IGNORED_THINKING` (2 scenarios): a press during the thinking pause did not stop the answer
- `LONG_PRESS_NO_EFFECT` (8 scenarios): holding the button for 2 s or more did nothing
- `GREEN_BUT_DEAF` (5 scenarios): the LED showed green (your turn) while the microphone was off for > 1.5 s
