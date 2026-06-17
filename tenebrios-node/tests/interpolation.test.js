// Tests del motor de interpolacion volumetrica 3D — port de test_interpolation.py.

import { describe, it, expect, beforeEach } from 'vitest';
import { HeatmapEngine } from '../src/heatmapEngine.js';

function fullSensorData() {
    return { t1: 24.0, t2: 26.0, t3: 25.0, t4: 27.0, t5: 23.0 };
}

describe('HeatmapEngine.interpolateVolume', () => {
    let engine;
    beforeEach(() => { engine = new HeatmapEngine(); });

    it('returns null with insufficient data', () => {
        engine.update({ t1: 25.0 });
        expect(engine.interpolateVolume()).toBeNull();
        engine.update({ t2: 26.0 });
        expect(engine.interpolateVolume()).toBeNull();
    });

    it('returns 5400 points with three or more sensors', () => {
        engine.update({ t1: 24.0, t2: 26.0, t3: 25.0 });
        const r = engine.interpolateVolume();
        expect(r).not.toBeNull();
        expect(Object.keys(r).sort()).toEqual(['value', 'x', 'y', 'z']);
        expect(r.x.length).toBe(5400);
        expect(r.value.length).toBe(5400);
    });

    it('produces values within HEATMAP_VMIN..VMAX', () => {
        engine.update(fullSensorData());
        const r = engine.interpolateVolume();
        for (const v of r.value) {
            expect(v).toBeGreaterThanOrEqual(14);
            expect(v).toBeLessThanOrEqual(35);
        }
    });

    it('rejects values outside valid range', () => {
        engine.update({ t1: 24.0, t2: 26.0, t3: 25.0, t4: 999.0 });
        expect(engine.getSensorValue('t4')).toBeNull();
    });
});

describe('HeatmapEngine.interpolateHumidityVolume', () => {
    it('returns volume when 3+ humidity sensors present', () => {
        const e = new HeatmapEngine();
        e.update({ h1: 50, h2: 60, h3: 55 });
        const r = e.interpolateHumidityVolume();
        expect(r).not.toBeNull();
        expect(r.value.length).toBe(5400);
        for (const v of r.value) {
            expect(v).toBeGreaterThanOrEqual(0);
            expect(v).toBeLessThanOrEqual(100);
        }
    });
});
