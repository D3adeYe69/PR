/* Copyright (c) 2021-25 MIT 6.102/6.031 course staff, all rights reserved.
 * Redistribution of original or derived work requires permission of course staff.
 */

import assert from 'node:assert';
import fs from 'node:fs';
import { Board } from '../src/board.js';


/**
 * Tests for the Board abstract data type.
 */
describe('Board', function() {
    
    // Helpers
    async function makeBoard(filename = 'boards/ab.txt'): Promise<Board> {
        return Board.parseFromFile(filename);
    }
    function parseBoard(text: string): { rows: number, cols: number, cells: Array<{ status: string, text?: string }>} {
        const lines = text.split(/\r?\n/);
        const [rowsS, colsS] = lines[0]!.split('x');
        const rows = parseInt(rowsS!), cols = parseInt(colsS!);
        const cells: Array<{ status: string, text?: string }> = [];
        for (let i = 1; i < lines.length; i++) {
            const parts = lines[i]!.split(' ');
            const status = parts[0]!;
            const txt = parts[1];
            cells.push({ status, text: txt });
        }
        return { rows, cols, cells };
    }
    function idxOf(r: number, c: number, cols: number): number { return r * cols + c; }

    it('look format and initial all down', async function() {
        const b = await makeBoard('boards/ab.txt');
        const state = await b.look('P1');
        const parsed = parseBoard(state);
        assert.strictEqual(parsed.rows * parsed.cols, parsed.cells.length);
        assert(parsed.cells.every(cell => cell.status === 'down'));
    });

    it('1-B first flip turns up and controls', async function() {
        const b = await makeBoard('boards/ab.txt');
        const before = parseBoard(await b.look('P1'));
        await b.flip('P1', 0, 0);
        const after = parseBoard(await b.look('P1'));
        assert.strictEqual(after.cells[idxOf(0,0,before.cols)]!.status, 'my');
    });

    it('1-C take control of already face-up free card', async function() {
        const b = await makeBoard('boards/ab.txt');
        await b.flip('P1', 0, 0); // turn up
        // relinquish by doing a mismatched second
        try { await b.flip('P1', 0, 1); } catch {}
        const afterMismatch = parseBoard(await b.look('P1'));
        assert.strictEqual(afterMismatch.cells[idxOf(0,0,afterMismatch.cols)]!.status, 'up');
        await b.flip('P2', 0, 0); // take control
        const after = parseBoard(await b.look('P2'));
        assert.strictEqual(after.cells[idxOf(0,0,after.cols)]!.status, 'my');
    });

    it('1-D waiting for controlled card', async function() {
        const b = await makeBoard('boards/ab.txt');
        await b.flip('A', 0, 0);
        const waitPromise = b.flip('B', 0, 0); // should wait
        // cause A to relinquish by failing second
        await assert.rejects(b.flip('A', 0, 0)); // second card controlled by self -> 2-B
        const stateB = await waitPromise;
        const parsed = parseBoard(stateB);
        assert.strictEqual(parsed.cells[idxOf(0,0,parsed.cols)]!.status, 'my');
    });

    it('2-B second flip fails on controlled card and relinquishes first', async function() {
        const b = await makeBoard('boards/ab.txt');
        await b.flip('P', 0, 0); // first
        // second flip same card (controlled by self) => fail
        await assert.rejects(b.flip('P', 0, 0));
        const state = parseBoard(await b.look('P'));
        // First card remains face up but not controlled after failure
        assert.strictEqual(state.cells[idxOf(0,0,state.cols)]!.status, 'up');
    });

    it('2-D match retains control; 3-A removes on next first move', async function() {
        const b = await makeBoard('boards/ab.txt');
        // board has A at (0,0) and A elsewhere; pick two As: (0,0) and (0,4)
        await b.flip('P', 0, 0);
        await b.flip('P', 0, 4); // match
        let view = parseBoard(await b.look('P'));
        assert.strictEqual(view.cells[idxOf(0,0,view.cols)]!.status, 'my');
        assert.strictEqual(view.cells[idxOf(0,4,view.cols)]!.status, 'my');
        // Next first move removes them
        await b.flip('P', 1, 1); // some other card
        view = parseBoard(await b.look('P'));
        assert.strictEqual(view.cells[idxOf(0,0,view.cols)]!.status, 'none');
        assert.strictEqual(view.cells[idxOf(0,4,view.cols)]!.status, 'none');
    });

    it('2-E mismatch relinquishes both; 3-B flips them down on next move', async function() {
        const b = await makeBoard('boards/ab.txt');
        // choose A then B for mismatch
        await b.flip('P', 0, 0); // A
        await assert.doesNotReject(b.flip('P', 1, 0)); // B
        let view = parseBoard(await b.look('P'));
        assert.strictEqual(view.cells[idxOf(0,0,view.cols)]!.status, 'up');
        assert.strictEqual(view.cells[idxOf(1,0,view.cols)]!.status, 'up');
        // Next first move flips down if still up and uncontrolled
        await b.flip('P', 2, 2); // some other
        view = parseBoard(await b.look('P'));
        assert.strictEqual(view.cells[idxOf(0,0,view.cols)]!.status, 'down');
        assert.strictEqual(view.cells[idxOf(1,0,view.cols)]!.status, 'down');
    });

    it('watch resolves when board changes', async function() {
        const b = await makeBoard('boards/ab.txt');
        const watchPromise = b.watch('W');
        await b.flip('P', 0, 0);
        const watched = await watchPromise;
        const parsed = parseBoard(watched);
        assert.strictEqual(parsed.cells.some(c => c.status === 'up' || c.status === 'my'), true);
    });

    it('map replaces cards and notifies watchers', async function() {
        const b = await makeBoard('boards/ab.txt');
        const watchPromise = b.watch('W2');
        const after = await b.map('X', async (card) => card === 'A' ? 'Z' : card);
        const parsed = parseBoard(after);
        assert(parsed.cells.filter(c => c.text === 'A').length === 0);
        await watchPromise; // should resolve due to change
    });
});


/**
 * Example test case that uses async/await to test an asynchronous function.
 * Feel free to delete these example tests.
 */
describe('async test cases', function() {
    it('reads a file asynchronously', async function() {
        const fileContents = (await fs.promises.readFile('boards/ab.txt')).toString();
        assert(fileContents.startsWith('5x5'));
    });
});
