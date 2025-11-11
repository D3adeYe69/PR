/* Copyright (c) 2021-25 MIT 6.102/6.031 course staff, all rights reserved.
 * Redistribution of original or derived work requires permission of course staff.
 */

import assert from 'node:assert';
import { Board } from './board.js';

/**
 * Example code for simulating a game.
 * 
 * PS4 instructions: you may use, modify, or remove this file,
 *   completing it is recommended but not required.
 * 
 * @throws Error if an error occurs reading or parsing the board
 */
async function simulationMain(): Promise<void> {
    // CLI: node dist/src/simulation.js [filename] [players] [tries] [minDelayMs] [maxDelayMs]
    const [, , argFilename, argPlayers, argTries, argMinDelay, argMaxDelay, argMaxSeconds] = process.argv;
    const filename = argFilename ?? 'boards/ab.txt';
    const parsedPlayers = parseInt(argPlayers ?? '');
    const parsedTries = parseInt(argTries ?? '');
    const parsedMinDelay = Number(argMinDelay ?? '');
    const parsedMaxDelay = Number(argMaxDelay ?? '');
    const players = Math.max(1, Number.isFinite(parsedPlayers) ? parsedPlayers : 4);
    const tries = Math.max(1, Number.isFinite(parsedTries) ? parsedTries : 100);
    const minDelayMs = Math.max(0, Number.isFinite(parsedMinDelay) ? parsedMinDelay : 0.1);
    const maxDelayMs = Math.max(minDelayMs, Number.isFinite(parsedMaxDelay) ? parsedMaxDelay : 0.2);
    const maxSeconds = Math.max(1, Number.isFinite(Number(argMaxSeconds)) ? Number(argMaxSeconds) : 10);

    const board: Board = await Board.parseFromFile(filename);
    // determine size from a look
    const header = (await board.look('sim_init')).split(/\r?\n/)[0] ?? '0x0';
    const [rowsS, colsS] = header.split('x');
    const boardRows = parseInt(rowsS ?? '0');
    const boardCols = parseInt(colsS ?? '0');

    // start up one or more players as concurrent asynchronous function calls
    const playerPromises: Array<Promise<void>> = [];
    const stats: Array<{
        id: string,
        moves: number,
        flipsFulfilled: number,
        flipsRejected: number,
        rejectedNoCard: number,
        rejectedControlled: number,
        start: number,
        end: number
    }> = [];
    for (let ii = 0; ii < players; ++ii) {
        const id = `player_${ii}`;
        stats.push({
            id,
            moves: 0,
            flipsFulfilled: 0,
            flipsRejected: 0,
            rejectedNoCard: 0,
            rejectedControlled: 0,
            start: Date.now(),
            end: 0
        });
        playerPromises.push(player(ii));
    }
    console.log('=== Memory Scramble Simulation ===');
    console.log(`Board: ${filename}`);
    console.log(`Size: ${boardRows} x ${boardCols}`);
    console.log(`Players: ${players}`);
    console.log(`Tries per player: ${tries}`);
    console.log(`Random delay per flip: [${minDelayMs} ms, ${maxDelayMs} ms]`);
    console.log('Legend:');
    console.log('  fulfilledFlips  = flips that completed without error (first or second)');
    console.log('  rejectedFlips   = flips that failed (broken down by reason)');
    console.log('  elapsedMs       = time spent by the player in the simulation');
    console.log('---------------------------------');
    // wait for all the players to finish, but don't hang forever: enforce a wall-clock timeout
    const finished = await waitAllWithTimeout(playerPromises, maxSeconds * 1000);
    // print statistics
    console.log(`Simulation results:${finished ? '' : ' (partial; timed out)'}`);
    // table columns
    const columns: string[] = ['player', 'fulfilledFlips', 'rejectedFlips', 'noCard', 'controlled', 'elapsedMs'];
    // collect rows to compute widths
    const tableRows: string[][] = [];
    let totalFulfilled = 0;
    let totalRejected = 0;
    let totalNoCard = 0;
    let totalControlled = 0;
    for (const s of stats) {
        const endTs = s.end === 0 ? Date.now() : s.end;
        const durationMs = endTs - s.start;
        totalFulfilled += s.flipsFulfilled;
        totalRejected += s.flipsRejected;
        totalNoCard += s.rejectedNoCard;
        totalControlled += s.rejectedControlled;
        tableRows.push([
            s.id,
            `${s.flipsFulfilled}`,
            `${s.flipsRejected}`,
            `${s.rejectedNoCard}`,
            `${s.rejectedControlled}`,
            `${durationMs}`
        ]);
    }
    // compute widths
    const minWidths = [8, 16, 16, 8, 11, 10];
    const widths = columns.map((h, i) => Math.max(h.length, minWidths[i] ?? 0, ...tableRows.map(r => r[i]!.length)));
    // print header and separator
    const headerLine = columns.map((h, i) => align(h, widths[i]!, i === 0 ? 'left' : 'right')).join('  ');
    const sepLine = widths.map(w => '─'.repeat(w)).join('──');
    console.log(headerLine);
    console.log(sepLine);
    // print rows
    for (const r of tableRows) {
        console.log(r.map((v, i) => align(v, widths[i]!, i === 0 ? 'left' : 'right')).join('  '));
    }
    console.log(sepLine);
    console.log(`Totals: fulfilledFlips=${totalFulfilled}, rejectedFlips=${totalRejected} (noCard=${totalNoCard}, controlled=${totalControlled})`);

    /** @param playerNumber player to simulate */
    async function player(playerNumber: number): Promise<void> {
        const playerId = `player_${playerNumber}`;

        for (let jj = 0; jj < tries; ++jj) {
            try {
                await timeout(minDelayMs + Math.random() * (maxDelayMs - minDelayMs));
                // choose a first card that still exists (avoid 'none')
                const view1 = parse(await board.look(playerId));
                const candidates1 = indicesWhere(view1, (cell) => cell.status !== 'none');
                if (candidates1.length === 0) { break; }
                const idx1 = candidates1[randomInt(candidates1.length)]!;
                const [r1, c1] = fromIndex(idx1, view1.cols);
                await board.flip(playerId, r1, c1);
                const s1 = stats[playerNumber];
                if (s1) { s1.moves++; s1.flipsFulfilled++; }
                await timeout(minDelayMs + Math.random() * (maxDelayMs - minDelayMs));
                // choose a second card that still exists (avoid 'none'); we cannot
                // tell if it's controlled by another player from our perspective, so some failures are expected
                const view2 = parse(await board.look(playerId));
                const candidates2 = indicesWhere(view2, (cell) => cell.status !== 'none');
                if (candidates2.length === 0) { continue; }
                const idx2 = candidates2[randomInt(candidates2.length)]!;
                const [r2, c2] = fromIndex(idx2, view2.cols);
                await board.flip(playerId, r2, c2);
                const s2 = stats[playerNumber];
                if (s2) { s2.moves++; s2.flipsFulfilled++; }
            } catch (err) {
                // Expected errors: 'no card at location' (after removals) and 'second card is controlled by a player' (2-B)
                const msg = `${err}`;
                const s = stats[playerNumber];
                if (s) {
                    s.flipsRejected++;
                    if (msg.includes('no card at location')) { s.rejectedNoCard++; }
                    else if (msg.includes('second card is controlled by a player')) { s.rejectedControlled++; }
                }
                // Do not spam console for expected failures
            }
        }
        const s = stats[playerNumber];
        if (s) { s.end = Date.now(); }
    }
}

/**
 * Random positive integer generator
 * 
 * @param max a positive integer which is the upper bound of the generated number
 * @returns a random integer >= 0 and < max
 */
function randomInt(max: number): number {
    return Math.floor(Math.random() * max);
}


/**
 * @param milliseconds duration to wait
 * @returns a promise that fulfills no less than `milliseconds` after timeout() was called
 */
async function timeout(milliseconds: number): Promise<void> {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, milliseconds);
    return promise;
}

simulationMain().catch(err => {
    console.error('Simulation error:', err);
    process.exitCode = 1;
});

// ---------------- helpers for parsing board state ----------------

function parse(text: string): { rows: number, cols: number, cells: Array<{ status: string, text?: string }> } {
    const lines = text.split(/\r?\n/);
    const [rowsS, colsS] = lines[0]!.split('x');
    const rows = parseInt(rowsS ?? '0'), cols = parseInt(colsS ?? '0');
    const cells: Array<{ status: string, text?: string }> = [];
    for (let i = 1; i < lines.length; i++) {
        const parts = lines[i]!.split(' ');
        const status = parts[0] ?? 'down';
        const t = parts[1];
        cells.push({ status, text: t });
    }
    return { rows, cols, cells };
}

function indicesWhere(view: { rows: number, cols: number, cells: Array<{ status: string, text?: string }> }, pred: (cell: { status: string, text?: string }) => boolean): number[] {
    const out: number[] = [];
    for (let i = 0; i < view.cells.length; i++) {
        if (pred(view.cells[i]!)) { out.push(i); }
    }
    return out;
}

function fromIndex(idx: number, cols: number): [number, number] {
    const r = Math.floor(idx / cols);
    const c = idx % cols;
    return [r, c];
}

function padRight(s: string, width: number): string {
    if (s.length >= width) { return s; }
    return s + ' '.repeat(width - s.length);
}

function padLeft(s: string, width: number): string {
    if (s.length >= width) { return s; }
    return ' '.repeat(width - s.length) + s;
}

function align(s: string, width: number, mode: 'left' | 'right'): string {
    return mode === 'left' ? padRight(s, width) : padLeft(s, width);
}

async function waitAllWithTimeout(promises: Array<Promise<unknown>>, timeoutMs: number): Promise<boolean> {
    const timeout = new Promise<boolean>(res => setTimeout(() => res(false), timeoutMs));
    const all = Promise.all(promises).then(() => true).catch(() => true);
    return Promise.race([timeout, all]);
}
