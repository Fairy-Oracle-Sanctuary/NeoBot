import { runMixedEstimatorFromText } from "./estimator/mixedEstimator.js";
import { analyzePatternFromText } from "./patterns/service.js";

async function main() {
    const chunks = [];
    for await (const chunk of process.stdin) {
        chunks.push(chunk);
    }
    const osuText = Buffer.concat(chunks).toString("utf-8");

    if (!osuText || !osuText.trim()) {
        process.stdout.write(JSON.stringify({ error: "Empty beatmap content" }));
        process.exit(1);
    }

    const speedRate = parseFloat(process.argv[2] || "1.0") || 1.0;

    try {
        const options = { speedRate, withGraph: true };
        const result = runMixedEstimatorFromText(osuText, options);

        let patternCategory = "";
        let patternModeTag = "";
        let svAmount = 0;
        try {
            const patternResult = analyzePatternFromText(osuText);
            patternCategory = patternResult?.report?.Category || "";
            patternModeTag = patternResult?.report?.ModeTag || "";
            svAmount = patternResult?.report?.SVAmount || 0;
        } catch {
            patternCategory = "";
            patternModeTag = "";
            svAmount = 0;
        }

        process.stdout.write(JSON.stringify({
            star: result.star,
            column_count: result.columnCount,
            ln_ratio: result.lnRatio,
            est_diff: result.estDiff,
            numeric_difficulty: result.numericDifficulty,
            numeric_difficulty_hint: result.numericDifficultyHint,
            graph: result.graph || null,
            pattern_category: patternCategory,
            pattern_mode_tag: patternModeTag,
            sv_amount: svAmount,
        }));
    } catch (err) {
        process.stdout.write(JSON.stringify({ error: err.message || String(err) }));
        process.exit(1);
    }
}

main();
