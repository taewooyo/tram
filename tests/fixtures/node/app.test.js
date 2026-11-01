import test from 'node:test';
import assert from 'node:assert/strict';
import { greet } from './app.js';
test('greeting', () => assert.equal(greet('Tram'), 'Hello, Tram!'));
