// Warehouse robot simulation — the Rust half of the comparison.
// Idiomatic Rust: plain structs in a Vec, a Copy mission enum carrying an
// order INDEX (the natural Rust design — no Rc<Order> needed), field-disjoint
// &mut self methods. Logic, traversal order, and tie-breaks mirror
// warehouse.saw exactly; the printed checksums must match it.

const W: i64 = 64;
const ROBOTS: usize = 100;
const TICKS: i64 = 200_000;
const ORDER_EVERY: i64 = 1;
const PENDING_CAP: usize = 500;
const BATTERY_CAP: i64 = 1200;
const BATTERY_LOW: i64 = 150;
const CHARGE_RATE: i64 = 25;

struct Rng {
    state: u64,
}

impl Rng {
    fn next(&mut self) -> u64 {
        self.state = self
            .state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.state >> 33
    }
    fn below(&mut self, n: i64) -> i64 {
        (self.next() % (n as u64)) as i64
    }
}

#[derive(Clone, Copy)]
enum Mission {
    Idle,
    ToPickup(usize),
    ToDropoff(usize),
    Charging,
}

struct Order {
    px: i64,
    py: i64,
    dx: i64,
    dy: i64,
}

struct Robot {
    x: i64,
    y: i64,
    battery: i64,
    delivered: i64,
    mission: Mission,
}

fn dist(ax: i64, ay: i64, bx: i64, by: i64) -> i64 {
    (ax - bx).abs() + (ay - by).abs()
}

struct Sim {
    robots: Vec<Robot>,
    orders: Vec<Order>,
    pending: Vec<usize>,
    pending_head: usize,
    rng: Rng,
    delivered: i64,
    steps: i64,
}

impl Sim {
    fn robot_idle(&self, r: usize) -> bool {
        matches!(self.robots[r].mission, Mission::Idle)
    }

    // Moves robot i one step toward (tx, ty); reports whether it now stands there.
    fn move_robot(&mut self, i: usize, tx: i64, ty: i64) -> bool {
        if self.robots[i].x == tx && self.robots[i].y == ty {
            return true;
        }
        if self.robots[i].x != tx {
            if self.robots[i].x < tx {
                self.robots[i].x += 1;
            } else {
                self.robots[i].x -= 1;
            }
        } else if self.robots[i].y < ty {
            self.robots[i].y += 1;
        } else {
            self.robots[i].y -= 1;
        }
        self.robots[i].battery -= 1;
        self.steps += 1;
        self.robots[i].x == tx && self.robots[i].y == ty
    }

    fn assign_pending(&mut self) {
        while self.pending_head < self.pending.len() {
            let oidx = self.pending[self.pending_head];
            let mut best: i64 = -1;
            let mut bestd: i64 = 1_000_000;
            for r in 0..ROBOTS {
                if self.robot_idle(r) {
                    let d = dist(
                        self.robots[r].x,
                        self.robots[r].y,
                        self.orders[oidx].px,
                        self.orders[oidx].py,
                    );
                    if d < bestd {
                        bestd = d;
                        best = r as i64;
                    }
                }
            }
            if best < 0 {
                return;
            }
            self.robots[best as usize].mission = Mission::ToPickup(oidx);
            self.pending_head += 1;
        }
    }

    fn step_robot(&mut self, i: usize) {
        let m = self.robots[i].mission;
        match m {
            Mission::Idle => {
                if self.robots[i].battery < BATTERY_LOW {
                    self.robots[i].mission = Mission::Charging;
                }
            }
            Mission::ToPickup(o) => {
                let tx = self.orders[o].px;
                let ty = self.orders[o].py;
                if self.move_robot(i, tx, ty) {
                    self.robots[i].mission = Mission::ToDropoff(o);
                }
            }
            Mission::ToDropoff(o) => {
                let tx = self.orders[o].dx;
                let ty = self.orders[o].dy;
                if self.move_robot(i, tx, ty) {
                    self.robots[i].mission = Mission::Idle;
                    self.robots[i].delivered += 1;
                    self.delivered += 1;
                }
            }
            Mission::Charging => {
                let sx = if self.robots[i].x < 32 { 0 } else { 63 };
                let sy = if self.robots[i].y < 32 { 0 } else { 63 };
                if self.move_robot(i, sx, sy) {
                    self.robots[i].battery += CHARGE_RATE;
                    if self.robots[i].battery >= BATTERY_CAP {
                        self.robots[i].battery = BATTERY_CAP;
                        self.robots[i].mission = Mission::Idle;
                    }
                }
            }
        }
    }

    fn tick(&mut self, t: i64) {
        if t % ORDER_EVERY == 0 && self.pending.len() - self.pending_head < PENDING_CAP {
            let px = self.rng.below(W);
            let py = self.rng.below(W);
            let dx = self.rng.below(W);
            let dy = self.rng.below(W);
            self.orders.push(Order { px, py, dx, dy });
            self.pending.push(self.orders.len() - 1);
        }
        self.assign_pending();
        for i in 0..ROBOTS {
            self.step_robot(i);
        }
    }
}

fn main() {
    let mut rng = Rng { state: 42 };
    let mut robots = Vec::new();
    for _ in 0..ROBOTS {
        let x = rng.below(W);
        let y = rng.below(W);
        robots.push(Robot {
            x,
            y,
            battery: BATTERY_CAP,
            delivered: 0,
            mission: Mission::Idle,
        });
    }
    let mut sim = Sim {
        robots,
        orders: Vec::new(),
        pending: Vec::new(),
        pending_head: 0,
        rng,
        delivered: 0,
        steps: 0,
    };

    for t in 0..TICKS {
        sim.tick(t);
    }

    let mut pos_hash: i64 = 0;
    let mut battery_sum: i64 = 0;
    for i in 0..ROBOTS {
        pos_hash = pos_hash
            .wrapping_mul(31)
            .wrapping_add(sim.robots[i].x * 64 + sim.robots[i].y);
        battery_sum += sim.robots[i].battery;
    }
    println!("created {}", sim.orders.len());
    println!("delivered {}", sim.delivered);
    println!("steps {}", sim.steps);
    println!("pos {}", pos_hash);
    println!("battery {}", battery_sum);
}
