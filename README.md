# PIXELBOX // OVERLOAD

A 16-colour, 8-bit arcade game built on the **PIXELBOX** seed engine with [Pyxel](https://github.com/kitao/pyxel).

The city grid is failing. Your maintenance bot has to recharge the reactor by collecting energy orbs while glitch drones hunt it down. Clear five waves to stabilise the grid. Lose all three hearts and the lights go out.

![Title screen](screenshots/title.png)

---

## Run it

Requires Python 3.8+ and a desktop with a display.

```bash
pip install -r requirements.txt
python main.py
```

(Alternative: `pyxel run main.py`)

Tested with Python 3.12 on Pyxel 2.9.9 and 3.0.1 (headless, under a virtual display).

---

## How to play

Win condition: clear **wave 5**. Loss condition: hearts reach zero.

Each wave has a **charge quota** shown in the top bar (`CHG 030/090`). Collect energy orbs to fill it:

| Wave | Charge needed | Orbs | Drones |
| :--- | :--- | :--- | :--- |
| 1 | 60 | 6 | 2 |
| 2 | 90 | 9 | 3 |
| 3 | 120 | 12 | 4 |
| 4 | 150 | 15 | 5 |
| 5 | 180 | 18 | 6 |

Clearing a wave repairs one heart (up to three) and scores `100 + 50 × wave`.

### Controls

| Input | Action |
| :--- | :--- |
| **Arrows / WASD** | Move |
| **SPACE** | Shockwave pulse in Free mode (damages drones, shoves orbs and crates). Jump in Gravity mode |
| **Left Click** | Deploy a crate barrier at the cursor. Costs 5 NRG, max 4 on screen |
| **Right Click** | BOOM. Crates near the cursor burst into orbs. Drones in range take 1 damage |
| **G** | Toggle Free (top-down) and Gravity (side-scroller) physics |
| **TAB** | Telemetry and 16-colour palette inspector |
| **ENTER** | Start or retry |
| **R** | Abort the run back to the title screen |
| **ESC** | Quit |

### Systems

- **Energy (NRG) vs. charge.** Each orb gives +10 to both. NRG is spent on crates. Charge only goes up and drives wave progress.
- **Drones.** Free mode: drones chase the bot. Gravity mode: they patrol the floor and hover on a sine wave. Contact costs one heart, then you get a short invulnerability window. Drones take two hits to destroy (pulse, boom, or a fast crate each deal 1).
- **Crates.** They burn out after 12 seconds, and the last few seconds blink. Running into a crate shoves it. A crate moving fast smashes any drone it hits. Booming a crate releases its energy as an orb, so a deployed crate can pay for itself.
- **Gravity mode.** Crates fall and land on the floor. Drones patrol at hover height. Jump with SPACE, W, or UP.

![Free mode](screenshots/gameplay-free.png)
![Gravity mode](screenshots/gameplay-gravity.png)

![Wave clear](screenshots/wave-clear.png)

![Game over](screenshots/game-over.png)
![Victory](screenshots/victory.png)

---

## Project structure

```text
pixelbox_overload/
├── main.py              # Game: title/play/wave-clear/game-over/victory state machine,
│                        #       bot physics, drone AI, crates, waves, HUD, title screen
├── engine.py            # Reusable primitives: Entity (AABB), ParticleSystem,
│                        #       FloatingTextManager, Camera (shake + flash), helpers
├── assets.py            # Hex-string sprites, chiptune sound bank, per-effect audio channels
├── requirements.txt     # pyxel>=2.0.0
├── screenshots/         # Images used in this README
├── PARTICIPANT_RULES.md # Challenge rules (from the organisers)
└── README.md
```

### Architecture notes

- **State machine (`main.py`).** `TITLE → PLAYING ⇄ WAVE_CLEAR → VICTORY` or `PLAYING → GAME_OVER`. Each state has its own input handling in `update()` and its own screens in `draw()`. The end screens ignore input for one second so a held key can't skip them.
- **Entities.** Orbs, crates, and drones are `engine.Entity` objects. Crate timers and drone phases live in each entity's `data` dict, so the engine itself is unchanged.
- **Audio routing.** Pyxel has four channels. `assets.SFX_CHANNEL` sends overlapping effects to separate channels so a pickup never cuts off a jump, and an explosion never cuts off the hurt sound.
- **Sprites and sounds are text.** Sprites are 8×8 hex grids and sounds are note strings, so they can be read and edited directly in code.

---

## Bugs fixed and changes from the seed

- **Python 3.8/3.9 crash.** `engine.py` used `list[int] | None` and `tuple[float, float]` in annotations, which are evaluated at import time on older Pythons. Added `from __future__ import annotations`. The codebase now needs Python 3.7+ by static analysis, and I ran it on 3.12.
- **Orbs bounced forever in gravity mode.** Velocity damping was skipped in gravity mode, so a pulse-launched orb would keep bouncing indefinitely. Orbs now always damp.
- **No audio feedback for damage or progress.** The seed's sound bank only covered jump, pickup, boom, and blip. Added hurt, pulse, wave, win, and lose sounds, plus per-effect channel routing.
- **Dead hit-points.** The seed had hit points but nothing could reduce them. Drones now do real damage, with invulnerability frames.
- **Sandbox → game.** No win state, no loss state, no progression. Added the title, five waves, a repair-on-clear rule, game over, victory, and best-run tracking.

---

## How it was tested

- **Launch.** `python main.py` runs under a virtual display with no errors.
- **Targeted mechanics checks (22 assertions).** Orb pickup economy, crate cost and cap, boom destroying drones and releasing crate orbs, pulse damage, contact damage with invulnerability, game over, restart after the input delay, wave clear with hearts repaired, final-wave victory, R returning to the title, gravity-mode orb damping, and arena clamping. All pass.
- **Scripted playthroughs.** A rule-based bot ran 8 full games. Four cleared all five waves and four were lost, so the difficulty is winnable but not trivial. No crashes.
- **Fuzz test.** 30,000 frames of random input across every state. Invariants held: HP in range, the player stays in the arena, resources never go negative, and the wave number stays valid.
- **Pyxel versions.** The targeted checks and the fuzz test pass on Pyxel 2.9.9 and 3.0.1.

Not tested: real audio output (the test container has no sound card, so the sound code runs but can't be heard), and gamepad input (the seed's gamepad mappings are kept, but I had no controller).

---

## PromptCraft

*(Edit this section to reflect your own prompts and experience. This version is based on the session that produced this build.)*

**The main prompt.** The brief asked the AI to act as a senior engineer on an incomplete codebase. It had to inspect the whole repo before changing anything, fix every bug without hiding errors, complete the missing features, make the project distinctive, test everything, and prepare a presentation. It also set a strict time budget and told the AI to implement rather than only suggest.

**What worked:**

- **"Read everything first."** Asking for a full inspection before any edits meant I found the real constraints first: the rules file requires Pyxel and `python main.py`, forbids other engines, and asks for a README with a PromptCraft section. The AI would otherwise have built something that breaks the rules.
- **Asking for real verification.** Requiring tests, not claims, led to a headless harness that drives the actual game loop. It caught an invalid sound note (octave 5, which Pyxel doesn't support) and a broken test-input path. Both would have been embarrassing in a live demo.
- **Screenshots as a check.** Looking at rendered frames caught a low-contrast control hint and a misleading "+1 HP" popup that no assertion would have flagged.
- **Balance by measurement.** A scripted bot that clears every wave, with free right-click booms, showed the boom was too strong. Halving its damage and doubling its cooldown produced a spread of outcomes.

**What didn't work:**

- **Mismatched framing.** The brief said "GitHub repo," "20 minutes," and "unique project," while the rules file said Pyxel, 60–90 minutes, and a README reflection. The rules were the authority, and the brief should have referenced them up front.
- **Harness bugs cost time.** My first mouse-position patch didn't set the real `pyxel.mouse_x` attribute, so boom tests silently hit the wrong spot. Testing the test harness early would have saved time.
- **Pyxel version drift.** The requirements file says `pyxel>=2.0.0`, but I had 3.0.1 installed. Checking against both 2.9.9 and 3.0.1 avoided surprises.

---

## Credits

Built on the PIXELBOX seed engine for the PromptCraft Final Round, using [Pyxel](https://github.com/kitao/pyxel) by kitao.
