/**
 * ExtractDropzone Component for InvestAI Enterprise.
 * Accessible drag-and-drop file upload with dual validation (extensions & 15 MB limit),
 * anti-flicker event counter, and institutional financial styling.
 */

import {
	AlertCircle,
	CheckCircle2,
	FileSpreadsheet,
	FileText,
	UploadCloud,
	X,
} from "lucide-react";
import type React from "react";
import { useRef, useState } from "react";

interface ExtractDropzoneProps {
	selectedFile: File | null;
	onFileSelect: (file: File | null) => void;
	disabled?: boolean;
	errorMessage?: string | null;
	onClearError?: () => void;
}

const ALLOWED_EXTENSIONS = [".csv", ".xlsx", ".xls"];
const MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024; // 15 MB

const SUPPORTED_BROKERS = [
	"Balanz Capital",
	"InvertirOnline (IOL)",
	"PPI",
	"Bull Market",
	"Caja de Valores",
	"Allaria",
];

function formatFileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export const ExtractDropzone: React.FC<ExtractDropzoneProps> = ({
	selectedFile,
	onFileSelect,
	disabled = false,
	errorMessage,
	onClearError,
}) => {
	const [isDragOver, setIsDragOver] = useState<boolean>(false);
	const [localError, setLocalError] = useState<string | null>(null);
	const dragCounterRef = useRef<number>(0);
	const inputRef = useRef<HTMLInputElement>(null);

	const displayError = errorMessage || localError;

	const validateAndSelect = (file: File) => {
		setLocalError(null);
		if (onClearError) onClearError();

		const lowerName = file.name.toLowerCase();
		const hasValidExt = ALLOWED_EXTENSIONS.some((ext) =>
			lowerName.endsWith(ext),
		);

		if (!hasValidExt) {
			setLocalError(
				`Extensión no soportada. Únicamente se admiten archivos ${ALLOWED_EXTENSIONS.join(
					", ",
				)}.`,
			);
			return;
		}

		if (file.size === 0) {
			setLocalError("El archivo seleccionado está vacío (0 bytes).");
			return;
		}

		if (file.size > MAX_FILE_SIZE_BYTES) {
			setLocalError(
				`El archivo excede el tamaño máximo permitido de 15 MB (tamaño actual: ${formatFileSize(
					file.size,
				)}).`,
			);
			return;
		}

		onFileSelect(file);
	};

	const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		dragCounterRef.current += 1;
		if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
			setIsDragOver(true);
		}
	};

	const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		dragCounterRef.current -= 1;
		if (dragCounterRef.current <= 0) {
			dragCounterRef.current = 0;
			setIsDragOver(false);
		}
	};

	const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
	};

	const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		setIsDragOver(false);
		dragCounterRef.current = 0;

		if (disabled) return;

		if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
			validateAndSelect(e.dataTransfer.files[0]);
		}
	};

	const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
		if (e.target.files && e.target.files.length > 0) {
			validateAndSelect(e.target.files[0]);
		}
	};

	const handleTriggerInput = () => {
		if (disabled) return;
		if (inputRef.current) {
			inputRef.current.value = "";
			inputRef.current.click();
		}
	};

	const handleRemoveFile = (e: React.MouseEvent) => {
		e.stopPropagation();
		setLocalError(null);
		if (onClearError) onClearError();
		onFileSelect(null);
		if (inputRef.current) {
			inputRef.current.value = "";
		}
	};

	const isExcel =
		selectedFile?.name.toLowerCase().endsWith(".xlsx") ||
		selectedFile?.name.toLowerCase().endsWith(".xls");

	return (
		<div className="w-full space-y-3">
			{/* Hidden Native File Input for Complete Accessibility */}
			<input
				ref={inputRef}
				type="file"
				accept=".csv,.xlsx,.xls,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
				className="hidden"
				disabled={disabled}
				onChange={handleFileInputChange}
				aria-label="Cargar extracto de broker"
			/>

			{/* Main Drag-and-Drop Surface */}
			<div
				onDragEnter={handleDragEnter}
				onDragLeave={handleDragLeave}
				onDragOver={handleDragOver}
				onDrop={handleDrop}
				onClick={handleTriggerInput}
				onKeyDown={(e) => {
					if (e.key === "Enter" || e.key === " ") {
						e.preventDefault();
						handleTriggerInput();
					}
				}}
				tabIndex={disabled ? -1 : 0}
				role="button"
				aria-disabled={disabled}
				className={`relative w-full rounded-2xl border-2 border-dashed p-8 transition-all cursor-pointer select-none text-center ${
					disabled
						? "border-slate-800 bg-slate-900/40 opacity-60 cursor-not-allowed"
						: isDragOver
							? "border-emerald-500 bg-emerald-500/10 shadow-lg shadow-emerald-500/10 ring-2 ring-emerald-500/30 scale-[1.005]"
							: selectedFile
								? "border-sky-500/60 bg-sky-950/20 shadow-md shadow-sky-950/30"
								: "border-slate-700/80 bg-slate-900/60 hover:border-slate-600 hover:bg-slate-900/90"
				}`}
			>
				{selectedFile ? (
					/* File Selected State */
					<div className="flex flex-col sm:flex-row items-center justify-between gap-4 p-2 pointer-events-none">
						<div className="flex items-center gap-4 text-left min-w-0">
							<div className="h-12 w-12 rounded-xl bg-sky-500/20 border border-sky-500/30 flex items-center justify-center text-sky-400 shrink-0">
								{isExcel ? (
									<FileSpreadsheet className="h-6 w-6 text-emerald-400" />
								) : (
									<FileText className="h-6 w-6 text-sky-400" />
								)}
							</div>
							<div className="min-w-0">
								<div className="flex items-center gap-2">
									<span
										className="font-mono text-sm font-semibold text-slate-100 truncate block max-w-xs sm:max-w-md"
										title={selectedFile.name}
									>
										{selectedFile.name}
									</span>
									<span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 shrink-0">
										{isExcel ? "EXCEL" : "CSV"}
									</span>
								</div>
								<div className="flex items-center gap-3 mt-1 text-xs text-slate-400 font-mono">
									<span>{formatFileSize(selectedFile.size)}</span>
									<span>•</span>
									<span className="text-emerald-400 flex items-center gap-1">
										<CheckCircle2 className="h-3.5 w-3.5" />
										Listo para procesar
									</span>
								</div>
							</div>
						</div>

						<div className="flex items-center gap-2 pointer-events-auto shrink-0">
							<button
								type="button"
								onClick={handleRemoveFile}
								disabled={disabled}
								className="px-3 py-1.5 rounded-lg bg-slate-800/80 hover:bg-rose-500/20 text-slate-300 hover:text-rose-300 border border-slate-700 hover:border-rose-500/30 text-xs font-medium transition-all flex items-center gap-1.5"
								title="Descartar archivo"
							>
								<X className="h-3.5 w-3.5" />
								<span>Descartar</span>
							</button>
						</div>
					</div>
				) : (
					/* Empty / Awaiting File State (Anti-flicker pointer-events-none on children) */
					<div className="flex flex-col items-center justify-center space-y-3 pointer-events-none">
						<div
							className={`h-14 w-14 rounded-2xl flex items-center justify-center transition-all ${
								isDragOver
									? "bg-emerald-500/20 text-emerald-400 scale-110"
									: "bg-slate-800/80 text-slate-400"
							}`}
						>
							<UploadCloud className="h-7 w-7" />
						</div>

						<div>
							<p className="text-sm font-medium text-slate-200">
								{isDragOver ? (
									<span className="text-emerald-400 font-semibold">
										Suelta el extracto aquí para procesarlo
									</span>
								) : (
									<>
										Arrastra y suelta tu extracto o{" "}
										<span className="text-sky-400 font-semibold underline decoration-sky-500/40 underline-offset-4">
											haz clic para examinar
										</span>
									</>
								)}
							</p>
							<p className="text-xs text-slate-400 mt-1">
								Formatos soportados: CSV, XLSX, XLS (máx. 15 MB)
							</p>
						</div>

						{/* Supported Broker Badges */}
						<div className="pt-2 flex flex-wrap items-center justify-center gap-1.5 max-w-lg">
							<span className="text-[10px] text-slate-400 font-mono mr-1">
								ALyCs:
							</span>
							{SUPPORTED_BROKERS.map((broker) => (
								<span
									key={broker}
									className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800/70 text-slate-300 border border-slate-700/60"
								>
									{broker}
								</span>
							))}
						</div>
					</div>
				)}
			</div>

			{/* Validation Error Banner */}
			{displayError && (
				<div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/50 flex items-center gap-2.5 text-xs text-rose-300">
					<AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
					<span className="flex-1">{displayError}</span>
					<button
						type="button"
						onClick={() => {
							setLocalError(null);
							if (onClearError) onClearError();
						}}
						className="text-rose-400 hover:text-rose-200"
						title="Cerrar advertencia"
					>
						<X className="h-3.5 w-3.5" />
					</button>
				</div>
			)}
		</div>
	);
};
