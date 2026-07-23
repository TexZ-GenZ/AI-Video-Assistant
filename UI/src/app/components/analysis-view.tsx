import { ResultsSection } from "./results-section";
import type { Results } from "../lib/videoApi";

interface AnalysisViewProps {
  results: Results;
}

/** The "Analysis" tab — the structured result cards for a completed job. */
export function AnalysisView({ results }: AnalysisViewProps) {
  return <ResultsSection results={results} />;
}
