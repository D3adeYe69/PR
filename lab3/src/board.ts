/* Copyright (c) 2021-25 MIT 6.102/6.031 course staff, all rights reserved.
 * Redistribution of original or derived work requires permission of course staff.
 */

/* eslint-disable @typescript-eslint/no-non-null-assertion, jsdoc/require-param, jsdoc/require-returns, @typescript-eslint/no-inferrable-types */
import assert from 'node:assert';
import fs from 'node:fs';
import { EventEmitter } from 'node:events';

/**
 * Memory Scramble Board ADT
 * 
 * - Mutable and concurrency-safe under Node's single-threaded event loop
 * - Supports multiple players interacting per the specified rules
 * - Provides wait-when-controlled semantics for first-card flips
 * - Provides observable board changes for watch()
 * - Provides a consistency-preserving map() operation
 */
export class Board {

    private readonly height: number;
    private readonly width: number;

    private readonly cells: Array<{
        card: string | null;     // null means removed
        faceUp: boolean;
        controller: string | null;
        waitQueue: Array<() => void>; // FIFO resolvers for players waiting to control this card as first card
    }>;

    // Per-player bookkeeping
    private readonly playerControlled: Map<string, Set<number>>; // indices currently controlled by player
    private readonly playerPendingMatched: Map<string, [number, number] | null>; // pair to remove on next first move
    private readonly playerLastRevealed: Map<string, Set<number>>; // cards to possibly flip down on next first move

    // Change watching
    private version: number = 0;
    private readonly changes: EventEmitter = new EventEmitter();

    // Concurrency for map(): per-cardvalue locks to update all instances atomically
    private readonly valueLocks: Map<string, Promise<void>> = new Map();
    // Concurrency for first-card acquisition: per-cell locks to serialize contenders
    private readonly cellLocks: Map<number, Promise<void>> = new Map();

    // Abstraction function:
    //   AF(height, width, cells, playerControlled, playerPendingMatched, playerLastRevealed) is a 2D
    //   grid of size height x width where each location is either empty (no card),
    //   or contains a card with a string value that may be face up or down, and may be controlled by
    //   a single player. Multiple players can interact concurrently following game rules.
    // Representation invariant:
    //   - height > 0, width > 0
    //   - cells.length === height * width
    //   - For each cell:
    //       card === null implies faceUp === false and controller === null
    //       controller !== null implies faceUp === true
    //   - For each player P:
    //       playerControlled.get(P) contains only indices i where cells[i].controller === P
    //       playerPendingMatched.get(P) either null or a pair [i,j] both currently controlled by P
    //   - No index is controlled by two different players
    // Safety from rep exposure:
    //   - All fields are private; no direct references to internal state are exposed
    //   - Methods return strings or new arrays/immutable values only
    //   - parseFromFile constructs fresh internal structures

    /**
     * Make a new empty board with given height and width.
     * All cells start with no card.
     * Internal use; prefer parseFromFile() to create a playable board.
     */
    public constructor(height: number = 0, width: number = 0) {
        this.height = height;
        this.width = width;
        const size = height * width;
        this.cells = Array.from({ length: size }, () => ({
            card: null,
            faceUp: false,
            controller: null,
            waitQueue: []
        }));
        this.playerControlled = new Map();
        this.playerPendingMatched = new Map();
        this.playerLastRevealed = new Map();
        this.checkRep();
    }

    private checkRep(): void {
        assert(this.height >= 0 && this.width >= 0);
        assert(this.cells.length === this.height * this.width);
        const seenControl = new Map<number, string>();
        for (let i = 0; i < this.cells.length; i++) {
            const c = this.cells[i]!;
            if (c.card === null) {
                assert(!c.faceUp);
                assert(c.controller === null);
            }
            if (c.controller !== null) {
                assert(c.faceUp);
                const prev = seenControl.get(i);
                assert(prev === undefined);
                seenControl.set(i, c.controller);
            }
        }
        for (const [player, set] of this.playerControlled) {
            for (const i of set) {
                assert(this.cells[i]!.controller === player);
            }
        }
        for (const [player, pair] of this.playerPendingMatched) {
            if (pair !== null) {
                const [i, j] = pair;
                assert(this.cells[i]!.controller === player);
                assert(this.cells[j]!.controller === player);
            }
        }
    }

    // ---------------- Core operations used by commands.ts ----------------

    /**
     * Return the board state text for a player.
     * Format:
     *   First line: "<rows>x<cols>"
     *   Then one line per cell, row-major:
     *     "none"                  if no card present
     *     "down"                  if face down
     *     "up <card>"             if face up and not controlled by player
     *     "my <card>"             if face up and controlled by player
     */
    public async look(playerId: string): Promise<string> {
        this.validatePlayer(playerId);
        const lines: string[] = [];
        lines.push(`${this.height}x${this.width}`);
        for (let r = 0; r < this.height; r++) {
            for (let c = 0; c < this.width; c++) {
                const idx = this.index(r, c);
                const cell = this.cells[idx]!;
                if (cell.card === null) {
                    lines.push('none');
                } else if (!cell.faceUp) {
                    lines.push('down');
                } else {
                    const status = cell.controller === playerId ? 'my' : 'up';
                    lines.push(`${status} ${cell.card}`);
                }
            }
        }
        return lines.join('\n');
    }

    /**
     * Flip a card according to rules. May wait if flipping a first card currently controlled by another player.
     */
    public async flip(playerId: string, row: number, column: number): Promise<string> {
        this.validatePlayer(playerId);
        this.validateBounds(row, column);

        // On starting a turn (first-card attempt), perform rule 3 cleanup
        const controlled = this.playerControlled.get(playerId) ?? new Set<number>();
        if (controlled.size === 0 || controlled.size === 2) {
            await this.finishPreviousPlay(playerId);
        }

        // Recompute controlled after cleanup
        const myControlled = this.playerControlled.get(playerId) ?? new Set<number>();
        const idx = this.index(row, column);
        const cell = this.cells[idx]!;

        // SECOND CARD attempt
        if (myControlled.size === 1) {
            const firstIdx = Array.from(myControlled)[0]!;
            if (cell.card === null) {
                // 2-A: no card, relinquish first
                this.releaseControl(firstIdx);
            this.addLastRevealed(playerId, firstIdx);
            this.bumpVersion();
                throw new Error('no card at location');
            }
            if (cell.faceUp && cell.controller !== null) {
                // 2-B: controlled by someone (or myself) => fail, relinquish first
                this.releaseControl(firstIdx);
            this.addLastRevealed(playerId, firstIdx);
            this.bumpVersion();
                throw new Error('second card is controlled by a player');
            }
            // 2-C: if down, flip up
            if (!cell.faceUp) {
                cell.faceUp = true;
            }
            // 2-D/E compare
            const firstCard = this.cells[firstIdx]!.card;
            const secondCard = cell.card;
            if (firstCard !== null && secondCard !== null && firstCard === secondCard) {
                // match: keep control of both
                cell.controller = playerId;
                myControlled.add(idx);
                this.playerControlled.set(playerId, myControlled);
                this.playerPendingMatched.set(playerId, [firstIdx, idx]);
            } else {
                // not match: relinquish both, keep them face up
                this.releaseControl(firstIdx);
                // ensure second is not controlled
                cell.controller = null;
                // remember to possibly flip them down on next first move
                this.addLastRevealed(playerId, firstIdx);
                this.addLastRevealed(playerId, idx);
            }
            this.bumpVersion();
            return this.look(playerId);
        }

        // FIRST CARD attempt
        if (cell.card === null) {
            // 1-A fail
            throw new Error('no card at location');
        }
        // Atomically acquire first-card control, handling face-down/up and concurrent contenders
        await this.acquireFirstCardControl(playerId, idx);
        return this.look(playerId);
    }

    /**
     * Replace cards using f while maintaining pairwise consistency for a given card value.
     * Implementation: for each distinct card value present at the start, compute f(value),
     * then atomically update all current instances of that value to the new value.
     */
    public async map(playerId: string, f: (card: string) => Promise<string>): Promise<string> {
        this.validatePlayer(playerId);
        // Snapshot distinct values present now
        const values = new Set<string>();
        for (const cell of this.cells) {
            if (cell.card !== null) { values.add(cell.card); }
        }
        for (const value of values) {
            const newValue = await f(value);
            await this.withValueLock(value, async () => {
                // Replace all current instances of `value` atomically
                let changed = false;
                for (const cell of this.cells) {
                    if (cell.card === value) {
                        if (newValue !== value) {
                            cell.card = newValue;
                            changed = true;
                        }
                    }
                }
                if (changed) { this.bumpVersion(); }
            });
        }
        return this.look(playerId);
    }

    /**
     * Wait until the board changes and then return the new state for playerId.
     */
    public async watch(playerId: string): Promise<string> {
        this.validatePlayer(playerId);
        const startVersion = this.version;
        if (this.versionChangedSince(startVersion)) {
            return this.look(playerId);
        }
        const { promise, resolve } = Promise.withResolvers<void>();
        const listener = (): void => {
            this.changes.off('change', listener);
            resolve();
        };
        this.changes.on('change', listener);
        await promise;
        return this.look(playerId);
    }

    /**
     * Make a new board by parsing a file.
     * 
     * PS4 instructions: the specification of this method may not be changed.
     * 
     * @param filename path to game board file
     * @returns a new board with the size and cards from the file
     * @throws Error if the file cannot be read or is not a valid game board
     */
    public static async parseFromFile(filename: string): Promise<Board> {
        let text: string;
        try {
            text = await fs.promises.readFile(filename, { encoding: 'utf8' });
        } catch (err) {
            throw new Error(`failed to read file: ${err}`);
        }
        const lines = text.split(/\r?\n/).filter(line => line.length > 0);
        if (lines.length < 1) { throw new Error('empty board file'); }
        const dims = lines[0]!.split('x');
        if (dims.length !== 2) { throw new Error('invalid dimensions line'); }
        const height = parseInt(dims[0]!);
        const width = parseInt(dims[1]!);
        if (!Number.isInteger(height) || !Number.isInteger(width) || height <= 0 || width <= 0) {
            throw new Error('invalid board dimensions');
        }
        const expectedCards = height * width;
        const cards = lines.slice(1);
        if (cards.length !== expectedCards) {
            throw new Error(`expected ${expectedCards} cards, got ${cards.length}`);
        }
        const board = new Board(height, width);
        for (let i = 0; i < expectedCards; i++) {
            const cell = board.cells[i]!;
            cell.card = cards[i]!;
            cell.faceUp = false;
            cell.controller = null;
        }
        board.bumpVersion();
        board.checkRep();
        return board;
    }

    // ---------------- Helper methods ----------------

    private index(row: number, column: number): number {
        return row * this.width + column;
    }

    private validateBounds(row: number, column: number): void {
        assert(Number.isInteger(row) && Number.isInteger(column));
        if (row < 0 || row >= this.height || column < 0 || column >= this.width) {
            throw new Error('row/column out of bounds');
        }
    }

    private validatePlayer(playerId: string): void {
        if (typeof playerId !== 'string' || !/^[A-Za-z0-9_]+$/.test(playerId)) {
            throw new Error('invalid playerId');
        }
        if (!this.playerControlled.has(playerId)) {
            this.playerControlled.set(playerId, new Set());
        }
        if (!this.playerPendingMatched.has(playerId)) {
            this.playerPendingMatched.set(playerId, null);
        }
        if (!this.playerLastRevealed.has(playerId)) {
            this.playerLastRevealed.set(playerId, new Set());
        }
    }

    private async finishPreviousPlay(playerId: string): Promise<void> {
        // 3-A remove matched pair if pending
        const pending = this.playerPendingMatched.get(playerId) ?? null;
        if (pending !== null) {
            const [i, j] = pending;
            // remove cards from board
            for (const idx of [i, j]) {
                const cell = this.cells[idx]!;
                cell.card = null;
                cell.faceUp = false;
                this.releaseControl(idx);
            }
            this.playerPendingMatched.set(playerId, null);
            this.bumpVersion();
        } else {
            // 3-B flip down previously revealed if still up and uncontrolled
            const last = this.playerLastRevealed.get(playerId) ?? new Set<number>();
            let changed = false;
            for (const idx of last) {
                const cell = this.cells[idx]!;
                if (cell.card !== null && cell.faceUp && cell.controller === null) {
                    cell.faceUp = false;
                    changed = true;
                }
            }
            if (last.size > 0) {
                last.clear();
                this.playerLastRevealed.set(playerId, last);
            }
            if (changed) { this.bumpVersion(); }
        }
        // ensure consistency
        this.checkRep();
    }

    private releaseControl(idx: number): void {
        const cell = this.cells[idx]!;
        const owner = cell.controller;
        if (owner !== null) {
            const set = this.playerControlled.get(owner);
            if (set !== undefined) {
                set.delete(idx);
                this.playerControlled.set(owner, set);
            }
        }
        cell.controller = null;
        // wake next waiter, if any
        const next = cell.waitQueue.shift();
        if (next) { setTimeout(next, 0); }
    }

    private addLastRevealed(playerId: string, idx: number): void {
        const set = this.playerLastRevealed.get(playerId) ?? new Set<number>();
        set.add(idx);
        this.playerLastRevealed.set(playerId, set);
    }

    private bumpVersion(): void {
        this.version++;
        // notify watchers asynchronously
        setImmediate(() => this.changes.emit('change', this.version));
    }

    private versionChangedSince(v: number): boolean {
        return this.version !== v;
    }

    private async waitForCardAvailability(idx: number): Promise<void> {
        const cell = this.cells[idx]!;
        if (cell.controller === null && cell.card !== null && cell.waitQueue.length === 0) {
            // immediately available, no need to wait
            return;
        }
        const { promise, resolve } = Promise.withResolvers<void>();
        cell.waitQueue.push(resolve);
        await promise;
    }

    /**
     * Acquire control of a first card atomically, ensuring that concurrent attempts
     * on a face-up free card serialize instead of racing.
     * Pre: card exists at idx.
     */
    private async acquireFirstCardControl(playerId: string, idx: number): Promise<void> {
        while (true) {
            // Enter per-cell critical section to decide whether to acquire immediately or enqueue to wait
            let waiter: Promise<void> | undefined;
            await this.withCellLock(idx, async () => {
                const cell = this.cells[idx]!;
                if (cell.card === null) {
                    throw new Error('no card at location');
                }
                if (cell.controller === null && cell.waitQueue.length === 0) {
                    // Acquire immediately
                    if (!cell.faceUp) {
                        cell.faceUp = true;
                    }
                    cell.controller = playerId;
                    const myControlled = this.playerControlled.get(playerId) ?? new Set<number>();
                    myControlled.add(idx);
                    this.playerControlled.set(playerId, myControlled);
                    this.bumpVersion();
                    waiter = undefined; // signal acquired
                } else {
                    // Must wait until available; enqueue a waiter
                    const { promise, resolve } = Promise.withResolvers<void>();
                    cell.waitQueue.push(resolve);
                    waiter = promise;
                }
            });
            if (waiter === undefined) {
                // acquired
                return;
            }
            // wait to be woken up by releaseControl(), then retry acquisition
            await waiter;
        }
    }

    private async withValueLock<T>(value: string, body: () => Promise<T>): Promise<T> {
        const current = this.valueLocks.get(value) ?? Promise.resolve();
        let release: (() => void) | undefined;
        const next = new Promise<void>(res => { release = res; });
        this.valueLocks.set(value, current.then(() => next));
        // Wait for prior tasks on this value to finish
        await current;
        try {
            return await body();
        } finally {
            // release lock
            release?.();
            // cleanup: if no further waiters chained, delete key later
            current.then(() => {
                // non-blocking best-effort cleanup
                if (this.valueLocks.get(value) === next) {
                    this.valueLocks.delete(value);
                }
            }).catch(() => { /* ignore */ });
        }
    }

    private async withCellLock<T>(idx: number, body: () => Promise<T>): Promise<T> {
        const current = this.cellLocks.get(idx) ?? Promise.resolve();
        let release: (() => void) | undefined;
        const next = new Promise<void>(res => { release = res; });
        this.cellLocks.set(idx, current.then(() => next));
        await current;
        try {
            return await body();
        } finally {
            release?.();
            current.then(() => {
                if (this.cellLocks.get(idx) === next) {
                    this.cellLocks.delete(idx);
                }
            }).catch(() => { /* ignore */ });
        }
    }
}
