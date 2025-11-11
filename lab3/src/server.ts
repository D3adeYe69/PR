/* Copyright (c) 2021-25 MIT 6.102/6.031 course staff, all rights reserved.
 * Redistribution of original or derived work requires permission of course staff.
 */

import assert from 'node:assert';
import process from 'node:process';
import { Server } from 'node:http';
import express, { Application } from 'express';
import { StatusCodes }  from 'http-status-codes';
import { Board } from './board.js';
import { look, flip, map, watch } from './commands.js';

type ParsedView = { rows: number, cols: number, cells: Array<{ status: string, text?: string }> };

function parseView(text: string): ParsedView {
    const lines = text.split(/\r?\n/);
    const [rowsS, colsS] = (lines[0] ?? '0x0').split('x');
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

function rngInt(max: number): number {
    return Math.floor(Math.random() * max);
}

async function sleep(ms: number): Promise<void> {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, ms);
    return promise;
}

/**
 * Start a game server using the given arguments.
 * 
 * PS4 instructions: you are advised *not* to modify this file.
 *
 * Command-line usage:
 *     npm start PORT FILENAME
 * where:
 * 
 *   - PORT is an integer that specifies the server's listening port number,
 *     0 specifies that a random unused port will be automatically chosen.
 *   - FILENAME is the path to a valid board file, which will be loaded as
 *     the starting game board.
 * 
 * For example, to start a web server on a randomly-chosen port using the
 * board in `boards/hearts.txt`:
 *     npm start 0 boards/hearts.txt
 * 
 * @throws Error if an error occurs parsing a file or starting a server
 */
async function main(): Promise<void> {
    const [portString, filename] 
        = process.argv.slice(2); // skip the first two arguments 
                                 // (argv[0] is node executable file, argv[1] is this script)
    if (portString === undefined) { throw new Error('missing PORT'); }
    const port = parseInt(portString);
    if (isNaN(port) || port < 0) { throw new Error('invalid PORT'); }
    if (filename === undefined) { throw new Error('missing FILENAME'); }
    
    const board = await Board.parseFromFile(filename);
    const server = new WebServer(board, port);
    await server.start();
}


/**
 * HTTP web game server.
 */
class WebServer {

    private readonly app: Application;
    private server: Server|undefined;
    private lastReport: string = 'no report yet';

    /**
     * Make a new web game server using board that listens for connections on port.
     * 
     * @param board shared game board
     * @param requestedPort server port number
     */
    public constructor(
        private readonly board: Board, 
        private readonly requestedPort: number
    ) {
        this.app = express();
        this.app.use((request, response, next) => {
            // allow requests from web pages hosted anywhere
            response.set('Access-Control-Allow-Origin', '*');
            next();
        });

        /*
         * GET /look/<playerId>
         * playerId must be a nonempty string of alphanumeric or underscore characters
         * 
         * Response is the board state from playerId's perspective, as described in the ps4 handout.
         */
        this.app.get('/look/:playerId', async(request, response) => {
            const { playerId } = request.params;
            assert(playerId);

            const boardState = await look(this.board, playerId);
            response
            .status(StatusCodes.OK) // 200
            .type('text')
            .send(boardState);
        });

        /*
         * GET /flip/<playerId>/<row>,<column>
         * playerId must be a nonempty string of alphanumeric or underscore characters;
         * row and column must be integers, 0 <= row,column < height,width of board (respectively)
         * 
         * Response is the state of the board after the flip from the perspective of playerID,
         * as described in the ps4 handout.
         */
        this.app.get('/flip/:playerId/:location', async(request, response) => {
            const { playerId, location } = request.params;
            assert(playerId);
            assert(location);

            const [ row, column ] = location.split(',').map( s => parseInt(s) );
            assert(row !== undefined && !isNaN(row));
            assert(column !== undefined && !isNaN(column));

            try {
                const boardState = await flip(this.board, playerId, row, column);
                response
                .status(StatusCodes.OK) // 200
                .type('text')
                .send(boardState);
            } catch (err) {
                response
                .status(StatusCodes.CONFLICT) // 409
                .type('text')
                .send(`cannot flip this card: ${err}`);
            }
        });

        /*
         * GET /replace/<playerId>/<oldcard>/<newcard>
         * playerId must be a nonempty string of alphanumeric or underscore characters;
         * oldcard and newcard must be nonempty strings.
         * 
         * Replaces all occurrences of oldcard with newcard (as card labels) on the board.
         * 
         * Response is the state of the board after the replacement from the the perspective of playerID,
         * as described in the ps4 handout.
         */
        this.app.get('/replace/:playerId/:fromCard/:toCard', async(request, response) => {
            const { playerId, fromCard, toCard } = request.params;
            assert(playerId);
            assert(fromCard);
            assert(toCard);

            const boardState = await map(this.board, playerId, async (card: string) => card === fromCard ? toCard : card);
            response
            .status(StatusCodes.OK) // 200
            .type('text')
            .send(boardState);
        });

        /*
         * GET /watch/<playerId>
         * playerId must be a nonempty string of alphanumeric or underscore characters
         * 
         * Waits until the next time the board changes (defined as any cards turning face up or face down, 
         * being removed from the board, or changing from one string to a different string).
         * 
         * Response is the new state of the board from the perspective of playerID,
         * as described in the ps4 handout.
         */
        this.app.get('/watch/:playerId', async(request, response) => {
            const { playerId } = request.params;
            assert(playerId);

            const boardState = await watch(this.board, playerId);
            response
            .status(StatusCodes.OK) // 200
            .type('text')
            .send(boardState);
        });

        /*
         * GET /simulate/<players>/<tries>/<minMs>/<maxMs>
         * Starts background bot players that make moves on the same shared board so changes are visible in the UI.
         * Returns immediately after launching the bots.
         */
        this.app.get('/simulate/:players/:tries/:minMs/:maxMs', async(request, response) => {
            const { players, tries, minMs, maxMs } = request.params;
            const { wait } = request.query as { wait?: string };
            const numPlayers = Math.max(1, parseInt(players ?? '4'));
            const numTries = Math.max(1, parseInt(tries ?? '100'));
            const minDelayMs = Math.max(0, Number(minMs ?? 0.1));
            const maxDelayMs = Math.max(minDelayMs, Number(maxMs ?? 2.0));

            const botPromises: Array<Promise<BotStats>> = [];
            const stats: BotStats[] = [];
            for (let i = 0; i < numPlayers; i++) {
                botPromises.push(runBot(this.board, `bot_${i}`, numTries, minDelayMs, maxDelayMs));
            }

            const runAll = async (): Promise<string> => {
                const results = await Promise.all(botPromises);
                stats.push(...results);
                const report = formatReport(stats);
                this.lastReport = report;
                console.log(report);
                return report;
            };

            const shouldWait = wait === '1' || wait === 'true';
            if (shouldWait) {
                const report = await runAll();
                response.status(StatusCodes.OK).type('text').send(report);
            } else {
                void runAll().catch(() => { /* ignore */ });
                response
                .status(StatusCodes.ACCEPTED)
                .type('text')
                .send(`started ${numPlayers} bot players with tries=${numTries}, delay=[${minDelayMs}, ${maxDelayMs}] ms; add ?wait=1 to wait for report or GET /report`);
            }
        });

        this.app.get('/report', async(_request, response) => {
            response.status(StatusCodes.OK).type('text').send(this.lastReport);
        });

        /*
         * GET /
         *
         * Response is the game UI as an HTML page.
         */
        this.app.use(express.static('public/'));
    }

    /**
     * Start this server.
     * 
     * @returns (a promise that) resolves when the server is listening
     */
    public start(): Promise<void> {
        const { promise, resolve } = Promise.withResolvers<void>();
        this.server = this.app.listen(this.requestedPort);
        this.server.on('listening', () => {
            console.log(`server now listening at http://localhost:${this.port}`);
            resolve();
        });
        return promise;
    }

    /**
     * @returns the actual port that server is listening at. (May be different
     *          than the requestedPort used in the constructor, since if
     *          requestedPort = 0 then an arbitrary available port is chosen.)
     *          Requires that start() has already been called and completed.
     */
    public get port(): number {
        const address = this.server?.address() ?? 'not connected';
        if (typeof(address) === 'string') {
            throw new Error('server is not listening at a port');
        }
        return address.port;
    }

    /**
     * Stop this server. Once stopped, this server cannot be restarted.
     */
     public stop(): void {
        this.server?.close();
        console.log('server stopped');
    }
}

/**
 * Background bot that makes random legal-ish moves visible to the UI.
 */
type BotStats = {
    id: string;
    moves: number;
    flipsFulfilled: number;
    flipsRejected: number;
    rejectedNoCard: number;
    rejectedControlled: number;
    start: number;
    end: number;
};

async function runBot(board: Board, playerId: string, tries: number, minDelayMs: number, maxDelayMs: number): Promise<BotStats> {
    const stats: BotStats = {
        id: playerId,
        moves: 0,
        flipsFulfilled: 0,
        flipsRejected: 0,
        rejectedNoCard: 0,
        rejectedControlled: 0,
        start: Date.now(),
        end: 0
    };
    for (let k = 0; k < tries; k++) {
        try {
            await sleep(minDelayMs + Math.random() * (maxDelayMs - minDelayMs));
            // first flip: choose a location that still has a card (not 'none')
            const view1 = parseView(await board.look(playerId));
            const candidates1: number[] = [];
            for (let i = 0; i < view1.cells.length; i++) {
                if (view1.cells[i]!.status !== 'none') { candidates1.push(i); }
            }
            if (candidates1.length === 0) { break; }
            const idx1 = candidates1[rngInt(candidates1.length)]!;
            const r1 = Math.floor(idx1 / view1.cols);
            const c1 = idx1 % view1.cols;
            await board.flip(playerId, r1, c1);
            stats.moves++;
            stats.flipsFulfilled++;

            await sleep(minDelayMs + Math.random() * (maxDelayMs - minDelayMs));
            // second flip: again choose a location that still has a card (not 'none')
            const view2 = parseView(await board.look(playerId));
            const candidates2: number[] = [];
            for (let i = 0; i < view2.cells.length; i++) {
                if (view2.cells[i]!.status !== 'none') { candidates2.push(i); }
            }
            if (candidates2.length === 0) { continue; }
            const idx2 = candidates2[rngInt(candidates2.length)]!;
            const r2 = Math.floor(idx2 / view2.cols);
            const c2 = idx2 % view2.cols;
            await board.flip(playerId, r2, c2);
            stats.moves++;
            stats.flipsFulfilled++;
        } catch (err) {
            // ignore expected failures; continue
            const msg = `${err}`;
            stats.flipsRejected++;
            if (msg.includes('no card at location')) { stats.rejectedNoCard++; }
            else if (msg.includes('second card is controlled by a player')) { stats.rejectedControlled++; }
        }
    }
    stats.end = Date.now();
    return stats;
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

function formatReport(stats: BotStats[]): string {
    const columns = ['player', 'fulfilledFlips', 'rejectedFlips', 'noCard', 'controlled', 'elapsedMs'];
    const rows: string[][] = [];
    let totalFulfilled = 0, totalRejected = 0, totalNoCard = 0, totalControlled = 0;
    for (const s of stats) {
        const elapsed = (s.end || Date.now()) - s.start;
        totalFulfilled += s.flipsFulfilled;
        totalRejected += s.flipsRejected;
        totalNoCard += s.rejectedNoCard;
        totalControlled += s.rejectedControlled;
        rows.push([
            s.id,
            `${s.flipsFulfilled}`,
            `${s.flipsRejected}`,
            `${s.rejectedNoCard}`,
            `${s.rejectedControlled}`,
            `${elapsed}`
        ]);
    }
    const minWidths = [8, 16, 16, 8, 11, 10];
    const widths = columns.map((h, i) => Math.max(h.length, minWidths[i] ?? 0, ...rows.map(r => r[i]!.length)));
    const headerLine = columns.map((h, i) => align(h, widths[i]!, i === 0 ? 'left' : 'right')).join('  ');
    const sepLine = widths.map(w => '─'.repeat(w)).join('──');
    const body = rows.map(r => r.map((v, i) => align(v, widths[i]!, i === 0 ? 'left' : 'right')).join('  ')).join('\n');
    const totals = `Totals: fulfilledFlips=${totalFulfilled}, rejectedFlips=${totalRejected} (noCard=${totalNoCard}, controlled=${totalControlled})`;
    return `Simulation results:\n${headerLine}\n${sepLine}\n${body}\n${sepLine}\n${totals}\n`;
}
await main();
