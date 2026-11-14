"""
PIXELBOX // OVERLOAD
====================
A complete 16-colour micro-arcade built on the PIXELBOX seed engine (Pyxel).

The city grid is failing. Your maintenance bot has to recharge the reactor by
collecting energy orbs. Each wave has a charge quota; glitch drones hunt the bot
while it works. Clear five waves to stabilise the grid. Three hearts of hit
points: lose them all and the grid goes dark.

Run with:
    python main.py        (or: pyxel run main.py)

Controls
  Arrow Keys / WASD : Move
  SPACE             : Shockwave pulse (Free mode) / Jump (Gravity mode)
  Left Click        : Deploy a crate barrier at the cursor (costs 5 NRG, max 4)
  Right Click       : BOOM. Crates near the cursor burst into orbs; drones are destroyed
  G                 : Toggle Free (top-down) and Gravity (side-scroller) physics
  TAB               : Telemetry & 16-colour palette inspector
  ENTER             : Start / retry
  R                 : Abort the run back to the title screen
  ESC               : Quit

Gameplay notes
  - Orbs add +10 to both NRG (spendable) and the wave charge (progress).
  - Crates burn out after 12 seconds. Running into a crate shoves it, and a fast
    crate smashes any drone it hits. Right-click BOOM releases the crate's orb.
  - Each wave you clear repairs one heart (up to three).
"""

from __future__ import annotations

import math
import random

import pyxel

from assets import draw_sprite, init_assets, play_sfx
from engine import Camera, Entity, FloatingTextManager, ParticleSystem, clamp, distance

SCREEN_W = 160
SCREEN_H = 120
FLOOR_Y = 104          # top of the floor strip (side-scroller mode)
TOP_Y = 14             # top edge of the playfield
LEFT_X = 4
RIGHT_X = SCREEN_W - 12
FPS = 30

MAX_HP = 3
FINAL_WAVE = 5
CRATE_COST = 5
MAX_CRATES = 4
CRATE_LIFE = 360       # frames (12 s) before a crate burns out
MAX_ORBS = 5
PULSE_RADIUS = 44
PULSE_COOLDOWN = 36    # frames
BOOM_RADIUS = 28
BOOM_COOLDOWN = 30     # frames (1 s)
IFRAMES = 40           # invulnerability after being hit
DRONE_HP = 2
DRONE_HOVER_Y = 52
WAVE_BANNER_FRAMES = 75
END_INPUT_DELAY = 30   # frames before the end screens accept a restart

# Game states
TITLE, PLAYING, WAVE_CLEAR, GAME_OVER, VICTORY = range(5)
STATE_NAMES = ["TITLE", "PLAY", "CLEAR", "OVER", "WIN"]


def wave_quota(wave: int) -> int:
    """Wave charge (NRG collected this wave) needed to finish the wave."""
    return 60 + 30 * (wave - 1)


def drones_for_wave(wave: int) -> int:
    """How many drones spawn during a wave."""
    return 1 + wave


class PixelBoxGame:
    def __init__(self, autorun: bool = True) -> None:
        pyxel.init(
            SCREEN_W,
            SCREEN_H,
            title="PIXELBOX // OVERLOAD",
            fps=FPS,
            quit_key=pyxel.KEY_ESCAPE,
        )
        init_assets()
        pyxel.mouse(False)  # we draw our own pixel crosshair
        self.best_score = 0
        self.best_wave = 0
        self.state = TITLE
        self.state_timer = 0
        self.reset_run()
        if autorun:
            pyxel.run(self.update, self.draw)

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------
    def reset_run(self) -> None:
        """Clear the world for a fresh run."""
        self.camera = Camera()
        self.particles = ParticleSystem()
        self.popups = FloatingTextManager()
        self.player = Entity(
            x=SCREEN_W // 2 - 4,
            y=SCREEN_H // 2 - 4,
            sprite="bot_idle",
            tag="player",
            hp=MAX_HP,
        )
        self.items: list[Entity] = []
        self.drones: list[Entity] = []
        self.gravity_mode = False
        self.show_debug = False
        self.wave = 1
        self.wave_charge = 0
        self.energy = 0
        self.score = 0
        self.invuln = 0
        self.pulse_radius = 0.0
        self.pulse_cooldown = 0
        self.boom_cooldown = 0
        self.orb_timer = 0
        self.drone_timer = 0
        self.drones_pending = 0

    def start_run(self) -> None:
        self.reset_run()
        self.state = PLAYING
        self.state_timer = 0
        for _ in range(3):
            x, y = self._random_open_spot(min_gap=24)
            self.spawn_orb(x, y)
        self._begin_wave(1)
        play_sfx("blip")

    def _begin_wave(self, wave: int) -> None:
        self.wave = wave
        self.wave_charge = 0
        self.drones_pending = drones_for_wave(wave)
        self.drone_timer = 45
        self.orb_timer = 0
        self.popups.spawn(f"WAVE {wave}", SCREEN_W // 2 - 14, 26, color=10, life=40)
        play_sfx("blip")

    def _complete_wave(self) -> None:
        self.score += 100 + 50 * self.wave
        healed = self.player.hp < MAX_HP
        self.player.hp = min(MAX_HP, self.player.hp + 1)
        for drone in self.drones:
            if drone.alive:
                cx, cy = drone.center()
                self.particles.burst(cx, cy, count=10, colors=[10, 9, 7], speed=2.0)
                drone.alive = False
        self.drones = []
        self.camera.shake(frames=6, intensity=2.0)
        if healed:
            self.popups.spawn("+1 HP", self.player.x - 4, self.player.y - 10, color=11)

        if self.wave >= FINAL_WAVE:
            self._end_run(VICTORY)
        else:
            self.state = WAVE_CLEAR
            self.state_timer = 0
            play_sfx("wave")

    def _end_run(self, state: int) -> None:
        self.state = state
        self.state_timer = 0
        self.best_score = max(self.best_score, self.score)
        self.best_wave = max(self.best_wave, self.wave)
        px, py = self.player.center()
        if state == GAME_OVER:
            self.camera.shake(frames=20, intensity=4.0)
            self.particles.burst(px, py, count=30, colors=[8, 9, 10, 7], speed=3.0)
            play_sfx("lose")
        else:
            self.particles.burst(px, py, count=24, colors=[10, 11, 12, 7], speed=2.6)
            play_sfx("win")

    # ------------------------------------------------------------------
    # Spawners
    # ------------------------------------------------------------------
    def spawn_orb(self, x: float, y: float) -> None:
        self.items.append(Entity(x=x, y=y, sprite="orb", tag="orb"))

    def spawn_crate(self, x: float, y: float) -> None:
        self.items.append(
            Entity(x=x, y=y, sprite="crate", tag="crate", hp=2, data={"life": CRATE_LIFE})
        )

    def _spawn_drone(self) -> None:
        px, py = self.player.center()
        x, y = float(LEFT_X), float(DRONE_HOVER_Y)
        for _ in range(12):
            if self.gravity_mode:
                x = float(random.choice([LEFT_X, RIGHT_X]))
                y = float(DRONE_HOVER_Y)
            else:
                edge = random.randrange(3)
                if edge == 0:
                    x, y = float(LEFT_X), random.uniform(TOP_Y, FLOOR_Y - 8)
                elif edge == 1:
                    x, y = float(RIGHT_X), random.uniform(TOP_Y, FLOOR_Y - 8)
                else:
                    x, y = random.uniform(LEFT_X, RIGHT_X), float(TOP_Y)
            if distance((x + 4, y + 4), (px, py)) >= 40:
                break
        self.drones.append(
            Entity(
                x=x,
                y=y,
                sprite="drone",
                tag="drone",
                hp=DRONE_HP,
                data={"dir": -1.0 if x > SCREEN_W / 2 else 1.0, "phase": random.uniform(0, math.tau)},
            )
        )

    def _random_open_spot(self, min_gap: float) -> tuple[float, float]:
        px, py = self.player.center()
        x, y = SCREEN_W / 2, SCREEN_H / 2
        for _ in range(12):
            x = random.uniform(LEFT_X + 4, RIGHT_X - 4)
            y = random.uniform(TOP_Y + 6, FLOOR_Y - 12)
            if distance((x, y), (px, py)) >= min_gap:
                break
        return x, y

    # ------------------------------------------------------------------
    # Frame update (30 FPS)
    # ------------------------------------------------------------------
    @staticmethod
    def _start_pressed() -> bool:
        return (
            pyxel.btnp(pyxel.KEY_RETURN)
            or pyxel.btnp(pyxel.KEY_SPACE)
            or pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT)
        )

    def update(self) -> None:
        if pyxel.btnp(pyxel.KEY_TAB):
            self.show_debug = not self.show_debug
            play_sfx("blip")

        if self.state == TITLE:
            if self._start_pressed():
                self.start_run()
            return

        if pyxel.btnp(pyxel.KEY_R):
            self.reset_run()
            self.state = TITLE
            self.state_timer = 0
            play_sfx("blip")
            return

        if self.state in (GAME_OVER, VICTORY):
            self.state_timer += 1
            if self.state_timer > END_INPUT_DELAY and self._start_pressed():
                self.start_run()
                return
            self._update_effects()
            return

        # PLAYING or WAVE_CLEAR
        if pyxel.btnp(pyxel.KEY_G):
            self.gravity_mode = not self.gravity_mode
            label = "GRAVITY" if self.gravity_mode else "FREE"
            self.popups.spawn(label, self.player.x - 4, self.player.y - 10, color=12)
            play_sfx("blip")

        self._update_player()
        self._update_mouse()
        self._update_items()
        self._update_drones()
        self._update_spawns()
        self._update_pulse()

        if self.invuln > 0:
            self.invuln -= 1
        if self.boom_cooldown > 0:
            self.boom_cooldown -= 1

        if self.state == PLAYING:
            if self.wave_charge >= wave_quota(self.wave):
                self._complete_wave()
        elif self.state == WAVE_CLEAR:
            self.state_timer += 1
            if self.state_timer >= WAVE_BANNER_FRAMES:
                self.state = PLAYING
                self._begin_wave(self.wave + 1)

        self._update_effects()

    def _update_effects(self) -> None:
        self.particles.update(gravity=0.08 if self.gravity_mode else 0.0)
        self.popups.update()
        self.camera.update()

    def _update_player(self) -> None:
        p = self.player
        speed = 2.0
        dx = 0.0
        dy = 0.0

        if pyxel.btn(pyxel.KEY_LEFT) or pyxel.btn(pyxel.KEY_A) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_LEFT):
            dx -= 1.0
            p.flip_x = True
        if pyxel.btn(pyxel.KEY_RIGHT) or pyxel.btn(pyxel.KEY_D) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_RIGHT):
            dx += 1.0
            p.flip_x = False

        if self.gravity_mode:
            p.vx = dx * speed
            p.vy = min(p.vy + 0.35, 4.0)
            on_ground = p.y >= FLOOR_Y - p.h
            jump = pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or pyxel.btnp(pyxel.KEY_SPACE)
            if jump and on_ground:
                p.vy = -4.2
                self.particles.burst(p.x + 4, p.y + 8, count=6, colors=[6, 7, 12])
                play_sfx("jump")
        else:
            if pyxel.btn(pyxel.KEY_UP) or pyxel.btn(pyxel.KEY_W) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_UP):
                dy -= 1.0
            if pyxel.btn(pyxel.KEY_DOWN) or pyxel.btn(pyxel.KEY_S) or pyxel.btn(pyxel.GAMEPAD1_BUTTON_DPAD_DOWN):
                dy += 1.0
            if dx != 0.0 and dy != 0.0:
                dx *= 0.7071
                dy *= 0.7071
            p.vx = dx * speed
            p.vy = dy * speed
            if pyxel.btnp(pyxel.KEY_SPACE) and self.pulse_cooldown == 0:
                self._pulse()

        p.update()
        p.x = clamp(p.x, 4.0, float(RIGHT_X))
        p.y = clamp(p.y, float(TOP_Y), float(FLOOR_Y - p.h))
        if self.gravity_mode and p.y >= FLOOR_Y - p.h:
            p.vy = 0.0  # landed

        moving = abs(p.vx) > 0.1 or (not self.gravity_mode and abs(p.vy) > 0.1)
        p.sprite = "bot_run" if (moving and (pyxel.frame_count // 4) % 2 == 0) else "bot_idle"

    def _update_mouse(self) -> None:
        raw_x, raw_y = pyxel.mouse_x, pyxel.mouse_y
        sx = clamp(raw_x, float(LEFT_X), float(RIGHT_X))
        sy = clamp(raw_y, float(TOP_Y), float(FLOOR_Y - 8))

        if pyxel.btnp(pyxel.MOUSE_BUTTON_LEFT):
            crates = sum(1 for item in self.items if item.tag == "crate")
            if crates >= MAX_CRATES:
                self._popup("MAX CRATES", sx - 10, sy - 6, color=8)
                play_sfx("blip")
            elif self.energy < CRATE_COST:
                self._popup(f"NEED {CRATE_COST} NRG", sx - 12, sy - 6, color=8)
                play_sfx("blip")
            else:
                self.energy -= CRATE_COST
                self.spawn_crate(sx, sy)
                self.popups.spawn("CRATE", sx - 4, sy - 6, color=9)
                self.particles.burst(sx + 4, sy + 4, count=8, colors=[7, 10, 12], speed=1.2)
                play_sfx("blip")

        if pyxel.btnp(pyxel.MOUSE_BUTTON_RIGHT) and self.boom_cooldown == 0:
            self._boom(raw_x, raw_y)

    def _popup(self, text: str, x: float, y: float, color: int) -> None:
        """Spawn a popup with its x kept on screen."""
        max_x = SCREEN_W - len(text) * 4 - 2
        self.popups.spawn(text, clamp(x, 2.0, float(max_x)), y, color=color)

    def _boom(self, mx: float, my: float) -> None:
        self.boom_cooldown = BOOM_COOLDOWN
        self.camera.shake(frames=8, intensity=2.5)
        self.particles.burst(mx, my, count=18, colors=[8, 9, 10, 7], speed=2.4)
        play_sfx("boom")
        self.popups.spawn("BOOM!", mx - 8, my - 4, color=8)

        drops: list[tuple[float, float]] = []
        for item in self.items:
            if item.tag == "crate" and item.alive:
                ix, iy = item.center()
                if distance((ix, iy), (mx, my)) < BOOM_RADIUS:
                    item.alive = False
                    drops.append((item.x, item.y))
                    self.particles.burst(ix, iy, count=10, colors=[9, 10, 7])
        for x, y in drops:
            self.spawn_orb(x, y)

        for drone in self.drones:
            if drone.alive and distance(drone.center(), (mx, my)) < BOOM_RADIUS:
                self._damage_drone(drone, 1)

    def _pulse(self) -> None:
        self.pulse_radius = 4.0
        self.pulse_cooldown = PULSE_COOLDOWN
        self.camera.shake(frames=5, intensity=1.5)
        play_sfx("pulse")
        px, py = self.player.center()
        for item in self.items:
            ix, iy = item.center()
            d = distance((ix, iy), (px, py))
            if 0 < d < PULSE_RADIUS:
                item.vx = (ix - px) / d * 3.0
                item.vy = (iy - py) / d * 3.0
        for drone in self.drones:
            if drone.alive and distance(drone.center(), (px, py)) < PULSE_RADIUS:
                self._damage_drone(drone, 1)

    def _update_pulse(self) -> None:
        if self.pulse_cooldown > 0:
            self.pulse_cooldown -= 1
        if self.pulse_radius > 0:
            self.pulse_radius += 4.5
            if self.pulse_radius > PULSE_RADIUS:
                self.pulse_radius = 0.0

    def _update_items(self) -> None:
        p = self.player
        remaining: list[Entity] = []
        for item in self.items:
            if item.tag == "crate":
                item.data["life"] -= 1
                if item.data["life"] <= 0:
                    item.alive = False
                    self.particles.burst(item.x + 4, item.y + 4, count=6, colors=[5, 9, 4], speed=1.0)
                    continue
                if self.gravity_mode:
                    item.vy = min(item.vy + 0.25, 3.5)
                # Running into a crate shoves it along
                if p.intersects(item):
                    item.vx = clamp(item.vx + p.vx * 0.3, -3.5, 3.5)
                    if not self.gravity_mode:
                        item.vy = clamp(item.vy + p.vy * 0.3, -3.5, 3.5)

            item.update()
            item.vx *= 0.85
            if not self.gravity_mode or item.tag == "orb":
                item.vy *= 0.85  # orbs always damp (fixes endless bouncing in gravity mode)

            # Arena walls
            if item.x < LEFT_X or item.x > RIGHT_X:
                item.vx *= -1
                item.x = clamp(item.x, float(LEFT_X), float(RIGHT_X))
            if self.gravity_mode and item.y >= FLOOR_Y - item.h and item.tag == "crate":
                item.y = float(FLOOR_Y - item.h)
                item.vy = 0.0
            elif item.y < TOP_Y or item.y > FLOOR_Y - item.h:
                item.vy *= -1
                item.y = clamp(item.y, float(TOP_Y), float(FLOOR_Y - item.h))

            # Fast crates smash drones
            if item.tag == "crate" and abs(item.vx) + abs(item.vy) > 1.2:
                for drone in self.drones:
                    if drone.alive and item.intersects(drone):
                        item.alive = False
                        self._damage_drone(drone, 1)
                        break

            # Orb pickup
            if item.tag == "orb" and p.intersects(item):
                item.alive = False
                self.energy += 10
                self.score += 10
                self.wave_charge += 10
                self.particles.burst(item.x + 4, item.y + 4, count=10, colors=[10, 9, 7])
                self.popups.spawn("+10", item.x - 4, item.y - 4, color=10)
                play_sfx("pickup")

            if item.alive:
                remaining.append(item)
        self.items = remaining

    def _damage_drone(self, drone: Entity, amount: int) -> None:
        cx, cy = drone.center()
        drone.hp -= amount
        if drone.hp > 0:
            self.particles.burst(cx, cy, count=6, colors=[8, 9, 7], speed=1.5)
            play_sfx("blip")
            return
        drone.alive = False
        self.score += 50
        self.energy += 5
        self.popups.spawn("+50", cx - 4, cy - 6, color=10)
        self.particles.burst(cx, cy, count=14, colors=[8, 9, 10, 7], speed=2.2)
        self.camera.shake(frames=4, intensity=1.2)
        play_sfx("boom")

    def _update_drones(self) -> None:
        p = self.player
        px, py = p.center()
        speed = 0.45 + 0.10 * self.wave
        for d in self.drones:
            if not d.alive:
                continue
            if self.gravity_mode:
                # Patrol back and forth while hovering in a sine wave
                d.vx = d.data["dir"] * speed * 1.6
                d.vy = 0.0
                d.update()
                if d.x < LEFT_X or d.x > RIGHT_X:
                    d.data["dir"] *= -1
                    d.x = clamp(d.x, float(LEFT_X), float(RIGHT_X))
                d.y = DRONE_HOVER_Y + math.sin(d.timer * 0.08 + d.data["phase"]) * 14
            else:
                # Chase the bot
                cx, cy = d.center()
                dx, dy = px - cx, py - cy
                dist = math.hypot(dx, dy)
                if dist > 0.5:
                    d.vx = dx / dist * speed
                    d.vy = dy / dist * speed
                d.update()
                d.x = clamp(d.x, float(LEFT_X), float(RIGHT_X))
                d.y = clamp(d.y, float(TOP_Y), float(FLOOR_Y - d.h))

            if self.invuln == 0 and self.state == PLAYING and p.intersects(d):
                self._hurt()
                if self.state != PLAYING:
                    return

        self.drones = [d for d in self.drones if d.alive]

    def _hurt(self) -> None:
        p = self.player
        p.hp -= 1
        self.invuln = IFRAMES
        self.camera.shake(frames=10, intensity=3.0)
        self.camera.flash(frames=2, color=8)
        self.particles.burst(p.x + 4, p.y + 4, count=12, colors=[8, 9, 7], speed=2.2)
        self.popups.spawn("-1 HP", p.x - 6, p.y - 8, color=8)
        play_sfx("hurt")
        if p.hp <= 0:
            self._end_run(GAME_OVER)

    def _update_spawns(self) -> None:
        if self.state != PLAYING:
            return

        self.orb_timer -= 1
        if self.orb_timer <= 0:
            self.orb_timer = 40
            orb_count = sum(1 for item in self.items if item.tag == "orb")
            if orb_count < MAX_ORBS:
                x, y = self._random_open_spot(min_gap=28)
                self.spawn_orb(x, y)

        if self.drones_pending > 0:
            self.drone_timer -= 1
            if self.drone_timer <= 0:
                self._spawn_drone()
                self.drones_pending -= 1
                self.drone_timer = max(40, 100 - self.wave * 10)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self) -> None:
        if self.state == TITLE:
            self._draw_title()
        elif self.camera.flash_frames > 0:
            pyxel.cls(self.camera.flash_color)
        else:
            self._draw_world()
            self._draw_hud()
            if self.state == WAVE_CLEAR:
                self._draw_panel(f"WAVE {self.wave} CLEAR", f"NEXT: WAVE {self.wave + 1}", 10)
            elif self.state == GAME_OVER:
                self._draw_end_panel("SYSTEM FAILURE", 8)
            elif self.state == VICTORY:
                self._draw_end_panel("GRID STABILIZED!", 11)
            if self.show_debug:
                self._draw_debug_overlay()
        draw_sprite("cursor", pyxel.mouse_x - 4, pyxel.mouse_y - 4)

    def _draw_world(self) -> None:
        cam_x, cam_y = self.camera.get_offset()
        pyxel.cls(1)

        for gx in range(0, SCREEN_W, 16):
            x = int(gx - cam_x)
            pyxel.line(x, 12, x, FLOOR_Y, 5 if gx % 32 == 0 else 1)
        for gy in range(16, FLOOR_Y + 1, 16):
            y = int(gy - cam_y)
            pyxel.line(0, y, SCREEN_W, y, 5 if gy % 32 == 0 else 1)

        pyxel.rectb(2, 12, SCREEN_W - 4, FLOOR_Y - 10, 12)
        if self.gravity_mode:
            pyxel.rect(2, FLOOR_Y, SCREEN_W - 4, 4, 3)

        if self.pulse_radius > 0:
            px, py = self.player.center()
            pyxel.circb(int(px - cam_x), int(py - cam_y), int(self.pulse_radius), 12)

        for item in self.items:
            if item.tag == "crate":
                if item.data["life"] < 90 and (pyxel.frame_count // 3) % 2 == 0:
                    continue  # blink while burning out
                item.draw(cam_x, cam_y)
            else:
                bob = math.sin((pyxel.frame_count + item.x) * 0.15) * 1.5
                draw_sprite("orb", item.x - cam_x, item.y + bob - cam_y)

        for d in self.drones:
            draw_sprite("drone", d.x - cam_x, d.y - cam_y, flip_x=d.vx < 0)

        hidden = self.invuln > 0 and (pyxel.frame_count // 2) % 2 == 0
        if not hidden:
            self.player.draw(cam_x, cam_y)

        self.particles.draw(cam_x, cam_y)
        self.popups.draw(cam_x, cam_y)

    def _draw_hud(self) -> None:
        pyxel.rect(0, 0, SCREEN_W, 11, 0)
        for i in range(MAX_HP):
            if i < self.player.hp:
                draw_sprite("heart", 4 + i * 9, 2)
            else:
                pyxel.rectb(4 + i * 9 + 2, 4, 4, 4, 5)
        quota = wave_quota(self.wave)
        pyxel.text(36, 3, f"W{self.wave}/{FINAL_WAVE}", 10)
        pyxel.text(58, 3, f"CHG {min(self.wave_charge, quota):03d}/{quota:03d}", 7)
        mode_tag = "GRAV" if self.gravity_mode else "FREE"
        pyxel.text(106, 3, f"[{mode_tag}]", 12)
        pyxel.text(144, 3, "TAB", 6)

        pyxel.rect(0, SCREEN_H - 11, SCREEN_W, 11, 0)
        pyxel.text(4, SCREEN_H - 8, f"NRG {self.energy:03d}  SC {self.score:05d}", 10)
        pyxel.text(92, SCREEN_H - 8, "L:CRATE R:BOOM", 6)

    @staticmethod
    def _text_center(y: int, s: str, color: int, shadow: int | None = None) -> None:
        x = (SCREEN_W - len(s) * 4) // 2
        if shadow is not None:
            pyxel.text(x + 1, y + 1, s, shadow)
        pyxel.text(x, y, s, color)

    def _draw_panel(self, title: str, subtitle: str, color: int) -> None:
        pyxel.rect(18, 42, 124, 36, 0)
        pyxel.rectb(18, 42, 124, 36, color)
        self._text_center(50, title, color)
        self._text_center(62, subtitle, 7)

    def _draw_end_panel(self, title: str, color: int) -> None:
        pyxel.rect(14, 30, 132, 60, 0)
        pyxel.rectb(14, 30, 132, 60, color)
        self._text_center(36, title, color, shadow=0)
        self._text_center(50, f"WAVES {self.wave}/{FINAL_WAVE}   SCORE {self.score:05d}", 7)
        self._text_center(60, f"BEST  WAVE {self.best_wave}   SCORE {self.best_score:05d}", 6)
        if self.state_timer > END_INPUT_DELAY and (pyxel.frame_count // 15) % 2 == 0:
            self._text_center(74, "ENTER: RETRY    R: TITLE", 10)

    def _draw_title(self) -> None:
        t = pyxel.frame_count
        pyxel.cls(1)
        for gx in range(0, SCREEN_W, 16):
            pyxel.line(gx, 0, gx, SCREEN_H, 5 if gx % 32 == 0 else 1)
        for gy in range(0, SCREEN_H, 16):
            pyxel.line(0, gy, SCREEN_W, gy, 5 if gy % 32 == 0 else 1)

        pyxel.rect(18, 10, 124, 46, 0)
        pyxel.rectb(18, 10, 124, 46, 12)
        self._text_center(18, "PIXELBOX", 10, shadow=0)
        self._text_center(31, "O V E R L O A D", 12, shadow=0)
        self._text_center(44, "GRID FAILING. RECHARGE IT.", 7)

        bob = math.sin(t * 0.1) * 2
        draw_sprite("orb", 44, 66 + math.sin(t * 0.15) * 2)
        draw_sprite("bot_run" if (t // 6) % 2 == 0 else "bot_idle", 76, 64 + bob)
        draw_sprite("drone", 108, 66 + math.sin(t * 0.12 + 1) * 2)

        if (t // 15) % 2 == 0:
            self._text_center(84, "PRESS ENTER TO START", 10)
        if self.best_score > 0:
            self._text_center(94, f"BEST: WAVE {self.best_wave}  SCORE {self.best_score:05d}", 6)
        self._text_center(103, "ARROWS MOVE  SPC PULSE/JUMP  G MODE", 7)
        self._text_center(111, "LCLK CRATE  RCLK BOOM  TAB INFO", 6)

    def _draw_debug_overlay(self) -> None:
        pyxel.rect(10, 18, SCREEN_W - 20, 84, 0)
        pyxel.rectb(10, 18, SCREEN_W - 20, 84, 7)
        pyxel.text(16, 23, "TELEMETRY & PALETTE", 11)
        pyxel.text(16, 32, f"ITEMS:{len(self.items)} DRONES:{len(self.drones)} PART:{len(self.particles.particles)}", 7)
        pyxel.text(16, 40, f"PLAYER:({int(self.player.x)},{int(self.player.y)}) MOUSE:({pyxel.mouse_x},{pyxel.mouse_y})", 7)
        pyxel.text(16, 48, f"STATE:{STATE_NAMES[self.state]} INV:{self.invuln} CD:{self.pulse_cooldown}", 7)
        pyxel.text(16, 58, "PYXEL COLORS (0-F):", 6)
        for col in range(16):
            cx = 16 + col * 8
            pyxel.rect(cx, 67, 7, 10, col)
            pyxel.text(cx + 2, 79, f"{col:x}", 7 if col != 7 else 1)


if __name__ == "__main__":
    PixelBoxGame()
