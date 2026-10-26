import { BookOpen } from "lucide-react";

/** A permanent tutorial entry point, with a one-time hint for independent explorers. */
export default function DemoTutorialAccess({ enabled, showHint, onStart, onDismissHint }) {
  return (
    <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-navy/10 bg-white px-5 py-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="font-semibold text-navy">{enabled ? "Guided tutorial is on" : "Explore at your own pace"}</p>
        <p className="mt-1 text-sm text-gray-600">
          {enabled
            ? "Follow the highlighted steps, or skip the guide at any time."
            : "A guided walkthrough is available whenever you need it."}
        </p>
      </div>
      <div className="flex flex-col items-start gap-2 sm:items-end">
        <button
          type="button"
          onClick={() => {
            onDismissHint?.();
            onStart();
          }}
          className={`inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-navy ${
            showHint
              ? "bg-navy text-white ring-4 ring-sky-200 shadow-lg animate-pulse"
              : "bg-navy text-white hover:opacity-90"
          }`}
        >
          <BookOpen size={17} />
          {enabled ? "Restart tutorial" : "Start tutorial"}
        </button>
        {showHint && (
          <div role="status" className="max-w-xs rounded-xl bg-lightblue/60 px-3 py-2 text-xs font-medium text-navy">
            Need help later? Click <strong>Start tutorial</strong> anytime.
            <button type="button" onClick={onDismissHint} className="ml-2 underline underline-offset-2">
              Got it
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
