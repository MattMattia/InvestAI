from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models.fx import Currency


class OrderState(str, Enum):
    """Lifecycle states of an order in the execution Finite State Machine (FSM)."""

    CREATED = "CREATED"  # Order drafted, awaiting pre-trade checks
    VALIDATED = "VALIDATED"  # Risk, portfolio limits, and liquidity checks passed
    SUBMITTED = "SUBMITTED"  # Dispatched to ALyC / Exchange (BYMA / DMA gateway)
    FILLED = "FILLED"  # Completely executed in market
    CANCELLED = "CANCELLED"  # Cancelled prior to fill
    REJECTED = "REJECTED"  # Denied by pre-trade validation, risk check, or market collar


class OrderSide(str, Enum):
    """Direction of the market transaction."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Execution pricing conditions."""

    MARKET = "MARKET"  # Executed immediately at current prevailing market price
    LIMIT = "LIMIT"  # Executed strictly at limit price or better


class InvalidOrderStateTransitionError(ValueError):
    """Raised when an illegal transition is attempted on an Order's FSM."""

    pass


# Deterministic FSM transition graph
VALID_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CREATED: {OrderState.VALIDATED, OrderState.REJECTED, OrderState.CANCELLED},
    OrderState.VALIDATED: {OrderState.SUBMITTED, OrderState.CANCELLED, OrderState.REJECTED},
    OrderState.SUBMITTED: {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED},
    OrderState.FILLED: set(),  # Terminal state
    OrderState.CANCELLED: set(),  # Terminal state
    OrderState.REJECTED: set(),  # Terminal state
}


class Order(BaseModel):
    """
    Domain Entity representing an actionable trade order governed by an explicit FSM.
    Strictly validated using Pydantic v2.
    """

    model_config = ConfigDict(validate_assignment=True, str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    portfolio_id: str | None = None
    ticker: str = Field(description="Asset ticker symbol, e.g. 'AAPL', 'AL30'")
    side: OrderSide = Field(description="BUY or SELL")
    order_type: OrderType = Field(description="MARKET or LIMIT")
    quantity: float = Field(gt=0.0, description="Quantity of shares or nominal units to trade")
    price: float | None = Field(
        default=None, description="Limit price. Mandatory for LIMIT orders, optional for MARKET"
    )
    currency: Currency = Field(default=Currency.ARS, description="Trading and settlement currency")
    state: OrderState = Field(default=OrderState.CREATED, description="Current FSM state")
    filled_quantity: float = Field(default=0.0, ge=0.0, description="Cumulative executed quantity")
    filled_avg_price: float | None = Field(
        default=None, ge=0.0, description="Volume-weighted average fill price"
    )
    rejection_reason: str | None = Field(default=None, description="Reason if rejected")
    cancellation_reason: str | None = Field(default=None, description="Reason if cancelled")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("El ticker no puede estar vacío.")
        return cleaned

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float | None) -> float | None:
        if v is not None and v <= 0.0:
            raise ValueError("El precio debe ser estrictamente positivo (> 0).")
        return v

    @model_validator(mode="after")
    def validate_order_type_and_price(self) -> "Order":
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError(
                "Una orden LIMIT requiere especificar un precio límite estrictamente positivo."
            )
        return self

    @property
    def is_terminal(self) -> bool:
        """Returns True if the order has reached a final state (FILLED, CANCELLED, REJECTED)."""
        return self.state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}

    def can_transition_to(self, target_state: OrderState) -> bool:
        """Evaluates whether transitioning to target_state is permitted from the current state."""
        return target_state in VALID_TRANSITIONS.get(self.state, set())

    def transition_to(
        self,
        new_state: OrderState,
        reason: str | None = None,
        filled_qty: float | None = None,
        filled_price: float | None = None,
    ) -> "Order":
        """
        Executes a valid state transition in the FSM or raises InvalidOrderStateTransitionError.
        """
        if not self.can_transition_to(new_state):
            raise InvalidOrderStateTransitionError(
                f"Transición de estado inválida: no se puede pasar de '{self.state.value}' a '{new_state.value}'."
            )

        self.state = new_state
        self.updated_at = datetime.now(UTC)

        if new_state == OrderState.REJECTED and reason:
            self.rejection_reason = reason
        elif new_state == OrderState.CANCELLED and reason:
            self.cancellation_reason = reason
        elif new_state == OrderState.FILLED:
            self.filled_quantity = filled_qty if filled_qty is not None else self.quantity
            self.filled_avg_price = filled_price if filled_price is not None else self.price

        return self

    def validate(self) -> "Order":
        """Convenience method to transition from CREATED to VALIDATED."""
        return self.transition_to(OrderState.VALIDATED)

    def submit(self) -> "Order":
        """Convenience method to transition from VALIDATED to SUBMITTED."""
        return self.transition_to(OrderState.SUBMITTED)

    def fill(
        self,
        filled_qty: float | None = None,
        filled_price: float | None = None,
    ) -> "Order":
        """Convenience method to transition from SUBMITTED to FILLED."""
        return self.transition_to(
            OrderState.FILLED,
            filled_qty=filled_qty,
            filled_price=filled_price,
        )

    def cancel(self, reason: str | None = None) -> "Order":
        """Convenience method to transition to CANCELLED."""
        return self.transition_to(OrderState.CANCELLED, reason=reason)

    def reject(self, reason: str) -> "Order":
        """Convenience method to transition to REJECTED."""
        return self.transition_to(OrderState.REJECTED, reason=reason)
