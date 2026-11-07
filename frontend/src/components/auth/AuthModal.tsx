/**
 * Modal Component for User Login & Registration.
 * Enforces strict credential hygiene (purging inputs on open/close/tab switch),
 * real-time password strength validation on registration, and quick demo credentials helper.
 */

import {
	AlertCircle,
	CheckCircle2,
	KeyRound,
	Lock,
	Mail,
	RefreshCw,
	ShieldCheck,
	UserCheck,
	X,
} from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { ApiError, type ValidationErrorDetail } from "@/lib/apiClient";
import type { InvestorProfile } from "@/types/api";

interface AuthModalProps {
	isOpen: boolean;
	onClose: () => void;
	initialMode?: "login" | "register";
}

export const AuthModal: React.FC<AuthModalProps> = ({
	isOpen,
	onClose,
	initialMode = "login",
}) => {
	const { login, register, isAuthenticated } = useAuth();
	const [mode, setMode] = useState<"login" | "register">(initialMode);

	// Form Fields
	const [email, setEmail] = useState<string>("");
	const [password, setPassword] = useState<string>("");
	const [fullName, setFullName] = useState<string>("");
	const [investorProfile, setInvestorProfile] =
		useState<InvestorProfile>("MODERATE");

	// Local UI State
	const [submitting, setSubmitting] = useState<boolean>(false);
	const [errorMessage, setErrorMessage] = useState<string | null>(null);
	const [validationErrors, setValidationErrors] = useState<
		ValidationErrorDetail[]
	>([]);

	const resetFormState = () => {
		setEmail("");
		setPassword("");
		setFullName("");
		setInvestorProfile("MODERATE");
		setErrorMessage(null);
		setValidationErrors([]);
	};

	// Purge all credentials when modal opens, closes, or auth state changes
	useEffect(() => {
		resetFormState();
		if (isOpen) {
			setMode(initialMode);
		}
	}, [isOpen, initialMode, isAuthenticated]);

	const handleModeSwitch = (targetMode: "login" | "register") => {
		setMode(targetMode);
		resetFormState();
	};

	const handleClose = () => {
		resetFormState();
		onClose();
	};

	// Handle ESC key to dismiss modal
	useEffect(() => {
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape" && isOpen) {
				handleClose();
			}
		};
		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [isOpen]);

	// Real-time password strength checks for Registration
	const passwordChecks = useMemo(() => {
		const hasMinLength = password.length >= 8;
		const hasUppercase = /[A-Z]/.test(password);
		const hasNumberOrSymbol = /[0-9!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(
			password,
		);
		const passedCount = [hasMinLength, hasUppercase, hasNumberOrSymbol].filter(
			Boolean,
		).length;
		return {
			hasMinLength,
			hasUppercase,
			hasNumberOrSymbol,
			isValid: hasMinLength && hasUppercase && hasNumberOrSymbol,
			passedCount,
		};
	}, [password]);

	if (!isOpen) return null;

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setErrorMessage(null);
		setValidationErrors([]);

		if (mode === "register" && !passwordChecks.isValid) {
			setErrorMessage(
				"La contraseña debe tener al menos 8 caracteres, una letra mayúscula y un número o símbolo.",
			);
			return;
		}

		setSubmitting(true);

		try {
			if (mode === "login") {
				await login({ email, password });
			} else {
				await register({
					email,
					password,
					full_name: fullName,
					investor_profile: investorProfile,
				});
			}
			handleClose();
		} catch (err: unknown) {
			if (err instanceof ApiError) {
				setErrorMessage(err.detail);
				if (err.validationErrors && err.validationErrors.length > 0) {
					setValidationErrors(err.validationErrors);
				}
			} else if (err instanceof Error) {
				setErrorMessage(err.message);
			} else {
				setErrorMessage(
					"Ocurrió un error inesperado al procesar la solicitud.",
				);
			}
		} finally {
			setSubmitting(false);
		}
	};

	const handleFillDemoCredentials = () => {
		setEmail("demo@investai.com");
		setPassword("InvestAI2026!");
		setErrorMessage(null);
		setValidationErrors([]);
	};

	return (
		<div
			className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
			onClick={handleClose}
		>
			<div
				className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full shadow-2xl overflow-hidden flex flex-col"
				onClick={(e) => e.stopPropagation()}
				role="dialog"
				aria-modal="true"
			>
				{/* Modal Header & Tabs */}
				<div className="flex items-center justify-between border-b border-slate-800 px-6 pt-5 pb-3">
					<div className="flex gap-4">
						<button
							type="button"
							onClick={() => handleModeSwitch("login")}
							className={`text-sm font-semibold pb-2 border-b-2 transition-colors ${
								mode === "login"
									? "border-sky-500 text-white"
									: "border-transparent text-slate-400 hover:text-slate-200"
							}`}
						>
							Iniciar Sesión
						</button>
						<button
							type="button"
							onClick={() => handleModeSwitch("register")}
							className={`text-sm font-semibold pb-2 border-b-2 transition-colors ${
								mode === "register"
									? "border-sky-500 text-white"
									: "border-transparent text-slate-400 hover:text-slate-200"
							}`}
						>
							Registrarse
						</button>
					</div>

					<button
						onClick={handleClose}
						className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
						aria-label="Cerrar modal"
					>
						<X className="h-5 w-5" />
					</button>
				</div>

				{/* Modal Form */}
				<form
					onSubmit={handleSubmit}
					autoComplete="off"
					className="p-6 flex flex-col gap-4"
				>
					{/* Error Banner */}
					{errorMessage && (
						<div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800/80 text-rose-300 text-xs flex items-start gap-2.5">
							<AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
							<div className="flex-1">
								<p className="font-semibold">{errorMessage}</p>
								{validationErrors.length > 0 && (
									<ul className="mt-1 list-disc list-inside space-y-0.5 text-rose-300/80">
										{validationErrors.map((v, i) => (
											<li key={i}>
												{v.field ? (
													<span className="font-mono">{v.field}: </span>
												) : null}
												{v.issue}
											</li>
										))}
									</ul>
								)}
							</div>
						</div>
					)}

					{/* Quick Demo Credentials Banner on Login */}
					{mode === "login" && (
						<div className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between gap-2">
							<div className="flex items-center gap-2 text-xs text-slate-300">
								<KeyRound className="h-4 w-4 text-sky-400 shrink-0" />
								<div>
									<span className="font-medium block">
										Cuenta Institucional Demo
									</span>
									<span className="text-[11px] text-slate-400 font-mono">
										demo@investai.com
									</span>
								</div>
							</div>
							<button
								type="button"
								onClick={handleFillDemoCredentials}
								className="px-2.5 py-1.5 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-500/30 text-[11px] font-semibold transition"
							>
								Usar Demo
							</button>
						</div>
					)}

					{/* Registration Extra Fields */}
					{mode === "register" && (
						<>
							<div>
								<label className="block text-xs font-medium text-slate-300 mb-1.5">
									Nombre Completo
								</label>
								<div className="relative">
									<UserCheck className="h-4 w-4 text-slate-500 absolute left-3 top-3" />
									<input
										type="text"
										required
										minLength={2}
										autoComplete="off"
										value={fullName}
										onChange={(e) => setFullName(e.target.value)}
										placeholder="Ej. Martín González"
										className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
									/>
								</div>
							</div>

							<div>
								<label className="block text-xs font-medium text-slate-300 mb-1.5">
									Perfil de Inversor Inicial
								</label>
								<select
									value={investorProfile}
									onChange={(e) =>
										setInvestorProfile(e.target.value as InvestorProfile)
									}
									className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
								>
									<option value="CONSERVATIVE">
										Conservador (Baja volatilidad, Renta fija)
									</option>
									<option value="MODERATE">
										Moderado (Equilibrio retorno/riesgo)
									</option>
									<option value="AGGRESSIVE">
										Agresivo (Renta variable, Crecimiento)
									</option>
								</select>
								<p className="text-[11px] text-emerald-400/90 mt-1 flex items-center gap-1">
									<ShieldCheck className="h-3.5 w-3.5" />
									Se asignará rol operativo TRADER por defecto para operar
									carteras.
								</p>
							</div>
						</>
					)}

					{/* Common Fields: Email and Password */}
					<div>
						<label className="block text-xs font-medium text-slate-300 mb-1.5">
							Correo Electrónico
						</label>
						<div className="relative">
							<Mail className="h-4 w-4 text-slate-500 absolute left-3 top-3" />
							<input
								type="email"
								name="investai_auth_email"
								required
								autoComplete="off"
								value={email}
								onChange={(e) => setEmail(e.target.value)}
								placeholder="analista@investai.market"
								className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
							/>
						</div>
					</div>

					<div>
						<label className="block text-xs font-medium text-slate-300 mb-1.5">
							Contraseña
						</label>
						<div className="relative">
							<Lock className="h-4 w-4 text-slate-500 absolute left-3 top-3" />
							<input
								type="password"
								name="investai_auth_password"
								required
								minLength={8}
								autoComplete="new-password"
								value={password}
								onChange={(e) => setPassword(e.target.value)}
								placeholder="••••••••••••"
								className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
							/>
						</div>

						{/* Password Strength Meter in Register Mode */}
						{mode === "register" && (
							<div className="mt-2.5 p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-2">
								<div className="flex items-center justify-between text-[11px]">
									<span className="text-slate-400">Fortaleza de clave:</span>
									<span
										className={`font-semibold ${
											passwordChecks.passedCount === 3
												? "text-emerald-400"
												: passwordChecks.passedCount === 2
													? "text-amber-400"
													: "text-rose-400"
										}`}
									>
										{passwordChecks.passedCount === 3
											? "Fuerte (Apta)"
											: passwordChecks.passedCount === 2
												? "Media (Incompleta)"
												: "Débil"}
									</span>
								</div>
								<div className="grid grid-cols-3 gap-1.5 h-1.5">
									{[1, 2, 3].map((step) => (
										<div
											key={step}
											className={`rounded-full transition-colors ${
												passwordChecks.passedCount >= step
													? passwordChecks.passedCount === 3
														? "bg-emerald-500"
														: "bg-amber-500"
													: "bg-slate-800"
											}`}
										/>
									))}
								</div>
								<ul className="space-y-1 text-[11px]">
									<li
										className={`flex items-center gap-1.5 ${
											passwordChecks.hasMinLength
												? "text-emerald-400"
												: "text-slate-400"
										}`}
									>
										<CheckCircle2 className="h-3 w-3 shrink-0" />
										Mínimo 8 caracteres
									</li>
									<li
										className={`flex items-center gap-1.5 ${
											passwordChecks.hasUppercase
												? "text-emerald-400"
												: "text-slate-400"
										}`}
									>
										<CheckCircle2 className="h-3 w-3 shrink-0" />
										Al menos una letra mayúscula (A-Z)
									</li>
									<li
										className={`flex items-center gap-1.5 ${
											passwordChecks.hasNumberOrSymbol
												? "text-emerald-400"
												: "text-slate-400"
										}`}
									>
										<CheckCircle2 className="h-3 w-3 shrink-0" />
										Al menos un número (0-9) o símbolo (!@#$%)
									</li>
								</ul>
							</div>
						)}
					</div>

					{/* Submit Button */}
					<button
						type="submit"
						disabled={
							submitting || (mode === "register" && !passwordChecks.isValid)
						}
						className="mt-2 w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm flex items-center justify-center gap-2 transition shadow-lg shadow-sky-600/30 disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{submitting ? (
							<>
								<RefreshCw className="h-4 w-4 animate-spin" />
								<span>Procesando...</span>
							</>
						) : mode === "login" ? (
							<span>Acceder a la Plataforma</span>
						) : (
							<span>Crear Cuenta Institucional</span>
						)}
					</button>
				</form>
			</div>
		</div>
	);
};
