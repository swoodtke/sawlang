// Warehouse robot simulation — Swift variant 2: the obvious performance
// issues removed. Structs instead of classes (no per-robot allocations, no
// ARC), the Mission enum carries an order INDEX instead of an Order
// reference (no retain/release on mission churn) — i.e., the Saw/Rust design
// written in Swift. Logic and traversal identical; checksums must match.

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

struct Order {
    let px: Int
    let py: Int
    let dx: Int
    let dy: Int
}

enum Mission {
    case idle
    case toPickup(Int)
    case toDropoff(Int)
    case charging
}

struct Robot {
    var x: Int
    var y: Int
    var battery: Int
    var delivered = 0
    var mission = Mission.idle
}

func dist(_ ax: Int, _ ay: Int, _ bx: Int, _ by: Int) -> Int {
    (ax > bx ? ax - bx : bx - ax) + (ay > by ? ay - by : by - ay)
}

struct Sim {
    var robots: [Robot]
    var orders: [Order] = []
    var pending: [Int] = []
    var pendingHead = 0
    var rng: Rng
    var delivered = 0
    var steps = 0

    func robotIdle(_ r: Int) -> Bool {
        if case .idle = robots[r].mission { return true }
        return false
    }

    mutating func moveRobot(_ i: Int, _ tx: Int, _ ty: Int) -> Bool {
        if robots[i].x == tx && robots[i].y == ty { return true }
        if robots[i].x != tx {
            if robots[i].x < tx { robots[i].x += 1 } else { robots[i].x -= 1 }
        } else {
            if robots[i].y < ty { robots[i].y += 1 } else { robots[i].y -= 1 }
        }
        robots[i].battery -= 1
        steps += 1
        return robots[i].x == tx && robots[i].y == ty
    }

    mutating func assignPending() {
        while pendingHead < pending.count {
            let oidx = pending[pendingHead]
            var best = -1
            var bestd = 1_000_000
            for r in 0..<ROBOTS {
                if robotIdle(r) {
                    let d = dist(robots[r].x, robots[r].y, orders[oidx].px, orders[oidx].py)
                    if d < bestd {
                        bestd = d
                        best = r
                    }
                }
            }
            if best < 0 { return }
            robots[best].mission = .toPickup(oidx)
            pendingHead += 1
        }
    }

    mutating func stepRobot(_ i: Int) {
        switch robots[i].mission {
        case .idle:
            if robots[i].battery < BATTERY_LOW {
                robots[i].mission = .charging
            }
        case .toPickup(let o):
            if moveRobot(i, orders[o].px, orders[o].py) {
                robots[i].mission = .toDropoff(o)
            }
        case .toDropoff(let o):
            if moveRobot(i, orders[o].dx, orders[o].dy) {
                robots[i].mission = .idle
                robots[i].delivered += 1
                delivered += 1
            }
        case .charging:
            let sx = robots[i].x < 32 ? 0 : 63
            let sy = robots[i].y < 32 ? 0 : 63
            if moveRobot(i, sx, sy) {
                robots[i].battery += CHARGE_RATE
                if robots[i].battery >= BATTERY_CAP {
                    robots[i].battery = BATTERY_CAP
                    robots[i].mission = .idle
                }
            }
        }
    }

    mutating func tick(_ t: Int) {
        if t % ORDER_EVERY == 0 && pending.count - pendingHead < PENDING_CAP {
            let px = rng.below(W)
            let py = rng.below(W)
            let dx = rng.below(W)
            let dy = rng.below(W)
            orders.append(Order(px: px, py: py, dx: dx, dy: dy))
            pending.append(orders.count - 1)
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
var sim = Sim(robots: robots, rng: rng)

for t in 0..<TICKS {
    sim.tick(t)
}

var posHash = 0
var batterySum = 0
for i in 0..<ROBOTS {
    posHash = posHash &* 31 &+ (sim.robots[i].x * 64 + sim.robots[i].y)
    batterySum += sim.robots[i].battery
}
print("created \(sim.orders.count)")
print("delivered \(sim.delivered)")
print("steps \(sim.steps)")
print("pos \(posHash)")
print("battery \(batterySum)")
