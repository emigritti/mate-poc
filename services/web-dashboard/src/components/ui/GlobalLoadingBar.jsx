import { useEffect, useState } from 'react';
import { useLoading } from '../../context/LoadingContext';

/**
 * GlobalLoadingBar — thin NProgress-style bar fixed at the very top of the viewport.
 *
 * Behaviour:
 *   • Appears immediately when a mutation fetch starts (POST/PUT/DELETE/PATCH).
 *   • Simulates progress: 15% → 55% → 80% while waiting.
 *   • Jumps to 100% as soon as the request resolves.
 *   • Fades out 350ms after reaching 100%.
 */
export default function GlobalLoadingBar() {
    const { loading } = useLoading();

    // width  : 0-100 (%)
    // visible: controls opacity / mount
    const [width,   setWidth]   = useState(0);
    const [visible, setVisible] = useState(false);
    const [fading,  setFading]  = useState(false);   // opacity-0 transition

    useEffect(() => {
        let t1, t2, t3;

        if (loading) {
            setFading(false);
            setVisible(true);
            setWidth(15);

            t1 = setTimeout(() => setWidth(55),  350);
            t2 = setTimeout(() => setWidth(80), 1400);
        } else {
            // Complete and fade out
            setWidth(100);
            t1 = setTimeout(() => setFading(true),  250);
            t2 = setTimeout(() => {
                setVisible(false);
                setWidth(0);
                setFading(false);
            }, 600);
        }

        return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
    }, [loading]);

    if (!visible) return null;

    return (
        <div
            className="fixed top-0 left-0 right-0 z-[9999] h-[3px] pointer-events-none"
            style={{ transition: 'opacity 350ms ease', opacity: fading ? 0 : 1 }}
        >
            {/* Main bar */}
            <div
                className="h-full bg-indigo-500"
                style={{
                    width: `${width}%`,
                    transition: width === 100
                        ? 'width 200ms ease-in'
                        : 'width 500ms cubic-bezier(0.4, 0, 0.2, 1)',
                }}
            />
            {/* Glow tip */}
            <div
                className="absolute top-0 h-full w-20 bg-gradient-to-r from-transparent via-indigo-300/70 to-transparent"
                style={{
                    left: `calc(${width}% - 40px)`,
                    transition: width === 100
                        ? 'left 200ms ease-in'
                        : 'left 500ms cubic-bezier(0.4, 0, 0.2, 1)',
                }}
            />
        </div>
    );
}
