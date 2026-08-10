// Warehouse robot simulation — the Swift half of the Saw-vs-Swift comparison.
// Idiomatic Swift OO: final classes for the coordinating objects (robots hold
// Order references through their mission enum, ARC manages them), a struct
// RNG, Array storage. The simulation logic, traversal order, and tie-breaks
// mirror warehouse.saw exactly; the printed checksums must match it.

let W = 64
let ROBOTS = 100
let TICKS = 200_000
let ORDER_EVERY = 1
let PENDING_CAP = 500
let BATTERY_CAP = 1200
let BATTERY_LOW = 150
let CHARGE_RATE = 25

struct Rng {
    var state: UInt64
    mutating func next() -> UInt64 {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return state >> 33
    }
    mutating func below(_ n: Int) -> Int {
        Int(next() % UInt64(n))
    }
}

final class Order {
    let id: Int
    let px: Int
    let py: Int
    let dx: Int
    let dy: Int
    init(id: Int, px: Int, py: Int, dx: Int, dy: Int) {
        self.id = id
        self.px = px
        self.py = py
        self.dx = dx
        self.dy = dy
    }
}

enum Mission {
    case idle
    case toPickup(Order)
    case toDropoff(Order)
    case charging
}

final class Robot {
    var x: Int
    var y: Int
    var battery: Int
    var delivered = 0
    var mission = Mission.idle
    init(x: Int, y: Int, battery: Int) {
        self.x = x
        self.y = y
        self.battery = battery
    }
    var isIdle: Bool {
        if case .idle = mission { return true }
        return false
    }
}

func dist(_ ax: Int, _ ay: Int, _ bx: Int, _ by: Int) -> Int {
    (ax > bx ? ax - bx : bx - ax) + (ay > by ? ay - by : by - ay)
}

final class Dispatcher {
    var robots: [Robot] = []
    var created = 0
    var pending: [Order] = []
    var pendingHead = 0
    var rng: Rng
    var delivered = 0
    var steps = 0

    init(rng: Rng) {
        self.rng = rng
    }

    // Moves robot one step toward (tx, ty); reports whether it now stands there.
    func moveRobot(_ r: Robot, _ tx: Int, _ ty: Int) -> Bool {
        if r.x == tx && r.y == ty { return true }
        if r.x != tx {
            if r.x < tx { r.x += 1 } else { r.x -= 1 }
        } else {
            if r.y < ty { r.y += 1 } else { r.y -= 1 }
        }
        r.battery -= 1
        steps += 1
        return r.x == tx && r.y == ty
    }

    func assignPending() {
        while pendingHead < pending.count {
            let order = pending[pendingHead]
            var best = -1
            var bestd = 1_000_000
            for r in 0..<ROBOTS {
                if robots[r].isIdle {
                    let d = dist(robots[r].x, robots[r].y, order.px, order.py)
                    if d < bestd {
                        bestd = d
                        best = r
                    }
                }
            }
            if best < 0 { return }
            robots[best].mission = .toPickup(order)
            pendingHead += 1
        }
    }

    func stepRobot(_ i: Int) {
        let r = robots[i]
        switch r.mission {
        case .idle:
            if r.battery < BATTERY_LOW {
                r.mission = .charging
            }
        case .toPickup(let o):
            if moveRobot(r, o.px, o.py) {
                r.mission = .toDropoff(o)
            }
        case .toDropoff(let o):
            if moveRobot(r, o.dx, o.dy) {
                r.mission = .idle
                r.delivered += 1
                delivered += 1
            }
        case .charging:
            let sx = r.x < 32 ? 0 : 63
            let sy = r.y < 32 ? 0 : 63
            if moveRobot(r, sx, sy) {
                r.battery += CHARGE_RATE
                if r.battery >= BATTERY_CAP {
                    r.battery = BATTERY_CAP
                    r.mission = .idle
                }
            }
        }
    }

    func tick(_ t: Int) {
        if t % ORDER_EVERY == 0 && pending.count - pendingHead < PENDING_CAP {
            let px = rng.below(W)
            let py = rng.below(W)
            let dx = rng.below(W)
            let dy = rng.below(W)
            pending.append(Order(id: created, px: px, py: py, dx: dx, dy: dy))
            created += 1
        }
        assignPending()
        for i in 0..<ROBOTS {
            stepRobot(i)
        }
    }
}

var rng = Rng(state: 42)
var robots: [Robot] = []
for _ in 0..<ROBOTS {
    let x = rng.below(W)
    let y = rng.below(W)
    robots.append(Robot(x: x, y: y, battery: BATTERY_CAP))
}
let sim = Dispatcher(rng: rng)
sim.robots = robots

for t in 0..<TICKS {
    sim.tick(t)
}

var posHash = 0
var batterySum = 0
for i in 0..<ROBOTS {
    posHash = posHash &* 31 &+ (sim.robots[i].x * 64 + sim.robots[i].y)
    batterySum += sim.robots[i].battery
}
print("created \(sim.created)")
print("delivered \(sim.delivered)")
print("steps \(sim.steps)")
print("pos \(posHash)")
print("battery \(batterySum)")
