# Lab 3 PR

## Setup

Requirements:
- Node.js 22.12.x (see `package.json "engines"`)
- npm 10+

Install dependencies:
```
npm install
```

TypeScript compile (optional, most scripts compile automatically):
```
npm run compile
```

## Running

The frontend consists of a single static file, `./public/index.html`.

The backend has to be written by you.
You can use any language and libraries.

This repository contains a starting point for the backend written in TypeScript.
You can run it like this:
```
npm install
npm start 8080 boards/ab.txt
```

That starts the HTTP server and serves the UI in `public/`. Open your browser to `http://localhost:8080/` and click "play!".

Commands:
- Start on a random available port:
  ```
  npm start 0 boards/zoom.txt
  ```
- Run the headless simulation (4 players, 100 moves each, 0.1–2ms delays):
  ```
  npm run simulation
  ```
  Custom parameters:
  ```
  # node dist/src/simulation.js [board] [players] [tries] [minDelayMs] [maxDelayMs] [timeoutSeconds]
  npm run simulation -- boards/ab.txt 4 100 0.1 2 10
  ```

- Run live, visible bots on the web UI (so you can watch moves):
  1) Start the server (examples):
     ```
     npm start 8080 boards/ab.txt
     npm start 8080 boards/15x15.txt
     ```
  2) Open `http://localhost:8080/`
  3) Start bots:
     ```
     http://localhost:8080/simulate/4/100/0.1/2
     ```
     - Add `?wait=1` to block and return a formatted report when finished.
     - Fetch last report later at `http://localhost:8080/report`

API Endpoints (used by the UI):
- `GET /look/:playerId` – returns the board for `playerId`
- `GET /flip/:playerId/:row,:col` – attempts a flip
- `GET /replace/:playerId/:fromCard/:toCard` – replace-card mapping
- `GET /watch/:playerId` – long-poll watch for changes
- `GET /simulate/:players/:tries/:minMs/:maxMs` – start N bot players; `?wait=1` to wait and return a report
- `GET /report` – return the last simulation report


## Design and documentation

This code follows the required module structure. In particular, `src/commands.ts` exports the required functions with the specified signatures, and is a thin wrapper around the `Board` ADT. Below we document the ADT’s representation invariants, safety from rep exposure, and the specifications for all externally-visible methods.

### Modules
- `src/board.ts` – Memory Scramble Board ADT (mutable, observable, concurrency-safe under Node’s event loop)
- `src/commands.ts` – required command API (`look`, `flip`, `map`, `watch`) delegating to `Board`
- `src/server.ts` – HTTP server that exposes the API to the UI; also provides `/simulate` and `/report`
- `src/simulation.ts` – optional headless simulator for stress and demonstration
- `test/*.ts` – unit and concurrency tests

The “commands” module requirements are met by keeping the function names, parameters, and documented behavior unmodified, and forwarding to the ADT.

### Board ADT

Abstraction function (AF):
- AF(height, width, cells, playerControlled, playerPendingMatched, playerLastRevealed) is a grid of size `height × width` where each location is either empty or contains a string-valued card, each card is either face up or down, and may be controlled by exactly one player. Players concurrently act on the board per the Memory Scramble rules.

Representation invariant (RI):
- `height > 0`, `width > 0`
- `cells.length === height * width`
- If `cell.card === null` then `cell.faceUp === false` and `cell.controller === null`
- If `cell.controller !== null` then `cell.faceUp === true`
- For each player P:
  - `playerControlled.get(P)` contains only indices whose `controller === P`
  - `playerPendingMatched.get(P)` is either `null` or a pair `[i, j]` both controlled by P
- No index is controlled by two players at once

Safety from rep exposure:
- All representation fields are `private`.
- Methods return only strings or fresh arrays/immutable values; no internal arrays/objects are exposed.
- `parseFromFile` constructs fresh, private state each time.

Concurrency and waiting:
- First-card acquisition uses a per-cell queue and an internal lock to serialize contenders and ensure fairness: a player trying to acquire control waits if the card is controlled or other contenders are queued.
- Second-card attempts never wait; they either succeed or fail immediately (rule 2-B), relinquishing the first card when required.
- `watch()` provides change notifications without busy-waiting.
- `map()` uses per-card-value locks to preserve pairwise consistency during replacement while allowing interleaving with other operations.

### Specifications (external API)

All functions throw an `Error` (rejected Promise) when preconditions are violated or the operation fails as specified by the rules. Player IDs must match `/^[A-Za-z0-9_]+$/`.

- `Board.parseFromFile(filename: string): Promise<Board>`
  - Requires: `filename` exists, is readable, first line like `HxW` with positive integers, and exactly `H*W` subsequent card strings
  - Effects: creates a fresh board with all cards face down and uncontrolled
  - Returns: a new `Board`

- `Board.look(playerId: string): Promise<string>`
  - Requires: `playerId` is a valid ID
  - Returns: board text view for `playerId`:
    - first line `HxW`
    - then row-major lines: `none`, `down`, `up <card>`, or `my <card>`

- `Board.flip(playerId: string, row: number, column: number): Promise<string>`
  - Requires: `playerId` valid, `row` and `column` in bounds
  - Behavior: follows full rules for first- and second-card attempts including waiting (1-D) only for first-card contention; second-card failures for 2-A/2-B relinquish the first card; 2-D/2-E enforce match/mismatch; 3-A/3-B are applied at the start of the next first-card attempt
  - Returns: new board text view for `playerId`
  - Throws: `Error('no card at location')`, `Error('second card is controlled by a player')`, `Error('row/column out of bounds')`, etc. per rules

- `Board.map(playerId: string, f: (card: string) => Promise<string>): Promise<string>`
  - Requires: `playerId` valid; `f` is a pure function over card strings
  - Effects: replaces all instances of each distinct card value with `f(value)`; preserves pairwise consistency during interleaving; does not change face-up/down or control status
  - Returns: board text view after replacement for `playerId`

- `Board.watch(playerId: string): Promise<string>`
  - Requires: `playerId` valid
  - Effects: suspends until the board’s version changes (card flips up/down, removal, or card string replacement), then returns the current board view
  - Returns: updated board text view for `playerId`

- `commands.look(board, playerId)`, `commands.flip(board, playerId, row, column)`, `commands.map(board, playerId, f)`, `commands.watch(board, playerId)`
  - The above are thin wrappers around the `Board` methods with the same specs and must not be renamed or have their signatures changed.

### Testing
- `test/board.test.ts`: primary rule coverage including 1-B/C/D, 2-B/D/E, 3-A/B, formatting, `watch`, and `map`
- `test/board.rare.test.ts`: edge and concurrency cases (races for first card, concurrent second-card attempts, out-of-bounds, invalid IDs, immediate `watch`, selective 3-B, multiple watchers)

### Simulation & Reporting
- Headless simulator: `npm run simulation -- boards/ab.txt 4 100 0.1 2 10`
- Live bots on the web board: `http://localhost:8080/simulate/4/100/0.1/2` (`?wait=1` to return a table); latest table at `http://localhost:8080/report`
