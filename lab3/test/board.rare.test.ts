/* Copyright (c) 2021-25 MIT 6.102/6.031 course staff, all rights reserved.
 * Redistribution of original or derived work requires permission of course staff.
 */

import assert from 'node:assert';
import { Board } from '../src/board.js';

describe('Board rare edges', function() {
    this.timeout(5000);

    async function makeBoard(filename = 'boards/ab.txt'): Promise<Board> {
        return Board.parseFromFile(filename);
    }
    function parseBoard(text: string) {
        const lines = text.split(/\r?\n/);
        const [rowsS, colsS] = lines[0]!.split('x');
        const rows = parseInt(rowsS!), cols = parseInt(colsS!);
        const cells = lines.slice(1).map(line => {
            const [status, txt] = line.split(' ');
            return { status, text: txt };
        });
        return { rows, cols, cells };
    }
    function idxOf(r: number, c: number, cols: number): number { return r * cols + c; }

    it('two players racing the same free face-up first card: only one acquires, other waits then acquires', async function() {
        const b = await makeBoard();
        await b.flip('P1', 0, 0); // up + controlled by P1
        // relinquish P1 by failing second so card remains face up & free
        await assert.rejects(b.flip('P1', 0, 0));
        // now two contenders try to take control as first move
        const a = b.flip('A', 0, 0);
        const c = b.flip('C', 0, 0);
        const first = await Promise.race([a, c]);
        const parsedFirst = parseBoard(first);
        assert.strictEqual(parsedFirst.cells[idxOf(0,0,parsedFirst.cols)]!.status, 'my');
        // cause owner to relinquish to allow the waiter to proceed
        const owner = parsedFirst.cells[idxOf(0,0,parsedFirst.cols)]!.status === 'my' ? 'A' : 'C';
        await assert.rejects(b.flip(owner, 0, 0)); // 2-B self-controlled
        const second = await Promise.all([a, c]).then(([sa, sc]) => sa.includes('my') ? sc : sa);
        const parsedSecond = parseBoard(second);
        assert.strictEqual(parsedSecond.cells[idxOf(0,0,parsedSecond.cols)]!.status, 'my');
    });

    it('both players attempt the SAME matching second card concurrently; exactly one completes the match', async function() {
        const b = await makeBoard();
        // Deterministic coordinates on boards/ab.txt: 'A' at (0,0), (0,2), (0,4)
        await b.flip('P1', 0, 0); // first A at (0,0)
        await b.flip('P2', 0, 2); // first A at (0,2)
        // Both attempt the same second card (0,4) which is also 'A'
        const p1Second = b.flip('P1', 0, 4);
        const p2Second = b.flip('P2', 0, 4);
        const results = await Promise.allSettled([p1Second, p2Second]);
        const successes = results.filter(r => r.status === 'fulfilled').length;
        const failures = results.filter(r => r.status === 'rejected').length;
        assert.strictEqual(successes, 1, 'exactly one second-card attempt should succeed');
        assert.strictEqual(failures, 1, 'exactly one second-card attempt should fail');
        // Check that exactly one player controls two cards (a matched pair pending removal)
        const s1 = parseBoard(await b.look('P1'));
        const s2 = parseBoard(await b.look('P2'));
        const p1My = s1.cells.filter(c => c.status === 'my').length;
        const p2My = s2.cells.filter(c => c.status === 'my').length;
        assert((p1My === 2 && p2My === 0) || (p1My === 0 && p2My === 2));
    });

    it('second-card never waits: immediate failure if controlled by other', async function() {
        const b = await makeBoard();
        await b.flip('X', 0, 0); // X controls
        await b.flip('Y', 1, 1); // Y first
        await assert.rejects(b.flip('Y', 0, 0)); // should reject immediately (2-B)
        const after = parseBoard(await b.look('Y'));
        // Y relinquished first; X still controls its original card
        assert.strictEqual(after.cells[idxOf(1,1,after.cols)]!.status, 'up');
    });

    it('flip fails on removed card (1-A) when another player removes matched pair before you act', async function() {
        const b = await makeBoard();
        // P removes a matched pair (A at (0,0) and (0,4)) across turns
        await b.flip('P', 0, 0);
        await b.flip('P', 0, 4); // match
        // Next first move removes them
        await b.flip('P', 1, 1);
        await assert.rejects(b.flip('Q', 0, 0)); // 1-A: no card there
    });

    it('watch returns immediately if a change already happened before watching call', async function() {
        const b = await makeBoard();
        await b.flip('P', 0, 0);
        const start = Date.now();
        await b.watch('W'); // should not block now that a change happened
        const elapsed = Date.now() - start;
        assert(elapsed < 50);
    });

    it('out-of-bounds flip throws', async function() {
        const b = await makeBoard();
        await assert.rejects(b.flip('P', -1, 0));
        await assert.rejects(b.flip('P', 0, -1));
        await assert.rejects(b.flip('P', 99, 0));
        await assert.rejects(b.flip('P', 0, 99));
    });

    it('invalid playerId rejected', async function() {
        const b = await makeBoard();
        await assert.rejects(b.look('bad id!'));
        await assert.rejects(b.flip('bad id!', 0, 0));
        await assert.rejects(b.map('bad id!', async c => c));
        await assert.rejects(b.watch('bad id!'));
    });

    it('3-B does not flip down if another player controls the revealed card', async function() {
        const b = await makeBoard();
        // P reveals two non-matching cards and relinquishes
        await b.flip('P', 0, 0);             // A
        await b.flip('P', 1, 0);             // B -> mismatch, both up, uncontrolled
        // Q takes control of one of P's revealed cards
        await b.flip('Q', 0, 0);             // take control of A
        // P starts next move; 3-B should flip down only the card not controlled by another (1,0)
        await b.flip('P', 0, 4);
        const viewP = parseBoard(await b.look('P'));
        const viewQ = parseBoard(await b.look('Q'));
        assert.strictEqual(viewP.cells[idxOf(1,0,viewP.cols)]!.status, 'down'); // flipped down
        assert.strictEqual(viewQ.cells[idxOf(0,0,viewQ.cols)]!.status, 'my');   // still up & controlled by Q
    });

    it('multiple watchers resolve on a single change', async function() {
        const b = await makeBoard();
        const w1 = b.watch('W1');
        const w2 = b.watch('W2');
        await b.flip('P', 0, 0);
        await Promise.all([w1, w2]);
    });

    it('2-A: second card empty causes failure and relinquishes first', async function() {
        const b = await makeBoard();
        // Create a removable match and remove it
        await b.flip('P', 0, 0);
        await b.flip('P', 0, 4); // match
        await b.flip('P', 1, 1); // triggers removal of (0,0) & (0,4)
        // Q starts a turn, then attempts second on removed location -> 2-A
        await b.flip('Q', 2, 2); // first
        await assert.rejects(b.flip('Q', 0, 0));
        const viewQ = parseBoard(await b.look('Q'));
        // Q relinquished first; second location remains none
        assert.strictEqual(viewQ.cells[idxOf(2,2,viewQ.cols)]!.status, 'up');
        assert.strictEqual(viewQ.cells[idxOf(0,0,viewQ.cols)]!.status, 'none');
    });

    it('2-C: second face-down card turns face up on attempt (mismatch case)', async function() {
        const b = await makeBoard();
        // Choose two different values to force mismatch; on boards/ab.txt (0,0)=A, (1,0)=B
        await b.flip('P', 0, 0); // first
        const before = parseBoard(await b.look('P'));
        assert.strictEqual(before.cells[idxOf(1,0,before.cols)]!.status, 'down');
        await b.flip('P', 1, 0); // second, turns up then mismatch
        const after = parseBoard(await b.look('P'));
        assert.strictEqual(after.cells[idxOf(1,0,after.cols)]!.status, 'up');
    });
});


