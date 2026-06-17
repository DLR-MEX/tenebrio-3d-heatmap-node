// Tests del parser de mensajes MQTT — port de test_mqtt_parser.py.

import { describe, it, expect } from 'vitest';
import { parseLvMessage } from '../src/mqttClient.js';

describe('parseLvMessage', () => {
    it('parses a valid /lv message into a single-key object', () => {
        const result = parseLvMessage('/v1.6/devices/tenebrios/t1/lv', Buffer.from('25.4'));
        expect(result).toEqual({ t1: 25.4 });
    });

    it('returns null for unknown variables', () => {
        expect(parseLvMessage('/v1.6/devices/tenebrios/foo/lv', Buffer.from('1.0'))).toBeNull();
    });

    it('returns null for non-numeric payload', () => {
        expect(parseLvMessage('/v1.6/devices/tenebrios/t1/lv', Buffer.from('abc'))).toBeNull();
    });

    it('returns null for malformed topic', () => {
        expect(parseLvMessage('/v1.6/devices/t1', Buffer.from('25'))).toBeNull();
    });

    it('parses humidity and ammonia variables', () => {
        expect(parseLvMessage('/v1.6/devices/tenebrios/h1/lv', Buffer.from('45.5'))).toEqual({ h1: 45.5 });
        expect(parseLvMessage('/v1.6/devices/tenebrios/amoniaco/lv', Buffer.from('0.5'))).toEqual({ amoniaco: 0.5 });
    });
});
