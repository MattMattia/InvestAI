/**
 * UploadProgressBar Component for InvestAI Enterprise.
 * Displays fluid multipart upload progress with visual percentage indicator,
 * pulsating animation, and accessible cancellation hook.
 */

import React from "react";
import { Loader2, XCircle } from "lucide-react";

interface UploadProgressBarProps {
  progress: number; // 0 to 100
  isUploading: boolean;
  onCancel?: () => void;
  fileName?: string;
}

export const UploadProgressBar: React.FC<UploadProgressBarProps> = ({
  progress,
  isUploading,
  onCancel,
  fileName,
}) => {
  if (!isUploading && progress <= 0) {
    return null;
  }

  const clampedProgress = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <div className="w-full rounded-xl bg-slate-900 border border-slate-800 p-4 space-y-3 shadow-lg">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 text-slate-300">
          <Loader2 className="h-4 w-4 animate-spin text-sky-400" />
          <span className="font-medium">
            {clampedProgress >= 100
              ? "Saneando y conciliando posiciones en backend..."
              : `Subiendo ${fileName ? `"${fileName}"` : "extracto"}...`}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-mono font-bold text-sky-400 text-sm">
            {clampedProgress}%
          </span>
          {onCancel && isUploading && (
            <button
              type="button"
              onClick={onCancel}
              className="text-xs text-rose-400 hover:text-rose-300 flex items-center gap-1 px-2 py-0.5 rounded bg-rose-950/40 border border-rose-800/40 hover:bg-rose-950/70 transition-colors"
              title="Cancelar subida"
            >
              <XCircle className="h-3.5 w-3.5" />
              <span>Cancelar</span>
            </button>
          )}
        </div>
      </div>

      {/* Progress Track */}
      <div className="w-full h-2.5 bg-slate-950 rounded-full overflow-hidden p-0.5 border border-slate-800">
        <div
          className="h-full bg-gradient-to-r from-sky-500 via-indigo-500 to-emerald-400 rounded-full transition-all duration-300 ease-out relative"
          style={{ width: `${clampedProgress}%` }}
        >
          {isUploading && clampedProgress < 100 && (
            <div className="absolute inset-0 bg-white/20 animate-pulse rounded-full" />
          )}
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono">
        <span>Transmisión multipart streaming</span>
        <span>Límite max: 15 MB</span>
      </div>
    </div>
  );
};

