// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title Tiwala Agent Wallet
/// @author Tiwala team
/// @notice An MSME's supplier-payment wallet operated by an AI agent. Each purchase
///         order is fully locked in escrow at creation and paid out in two
///         milestones: a down payment, then the balance after the owner attests
///         delivery.
/// @dev Permission tiers are enforced here, not in the agent's prompt.
///      OWNER (human): add suppliers, set limits, approve large deals, attest
///      delivery, dispute, extend deadlines, withdraw, pause.
///      AGENT (AI key): create deals, release down payments and balances, cancel
///      overdue deals; bounded by per-deal, daily and down-payment caps.
///
///      Invariants (checked by test/invariant):
///      I1. locked == sum over open deals of the amount not yet paid out.
///      I2. token.balanceOf(this) >= locked, unless the token issuer burned (see isUnderfunded).
///      I3. Before attestation the agent can have paid a supplier at most maxDownBps of a deal.
contract TiwalaAgentWallet is ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ------------------------------------------------------------------ types

    enum Status {
        None,
        Locked,
        DownPaid,
        Delivered,
        Completed,
        Refunded,
        Disputed
    }

    struct Deal {
        address supplier;
        uint256 total;
        uint16 downBps; // down payment in basis points (3000 = 30%)
        uint64 deadline; // expected delivery (unix seconds)
        uint64 deliveredAt; // set by confirmDelivery
        Status status;
        bool ownerApproved;
        bytes32 refHash; // keccak256 of the PO reference; full text is in DealCreated
    }

    struct SupplierInfo {
        bool listed;
        uint64 activeAt; // payable from this time (anti induced-transfer delay)
        uint32 completed; // delivered on time
        uint32 late; // delivered late, cancelled after down payment, or refunded in dispute
    }

    // ----------------------------------------------------------------- errors

    error NotOwner();
    error NotOperator();
    error IsPaused();
    error ZeroAddress();
    error AgentIsOwner();
    error BadSupplier();
    error SupplierNotActive();
    error SupplierRemoved();
    error AmountOutOfRange();
    error BadBps();
    error DownPaymentAboveCap();
    error DeadlineInPast();
    error InsufficientFreeBalance();
    error WrongStatus(Status actual);
    error ApprovalRequired();
    error DailyCapExceeded();
    error NotOverdue();
    error MustExtend();

    // ------------------------------------------------------------------ state

    uint16 internal constant BPS = 10_000;

    IERC20 public immutable token;
    address public immutable owner;
    address public agent;
    bool public paused;

    uint256 public perDealCap;
    uint256 public dailyCap; // agent-initiated payouts per UTC day
    uint256 public approvalThreshold; // agent deals above this need owner approval
    uint64 public supplierDelay;
    uint16 public maxDownBps = 5_000; // DP_max for agent-created deals
    uint64 public grace = 2 days; // agent may auto-cancel only after deadline + grace

    uint256 public locked; // funds committed to open deals
    uint256 public spentToday;
    uint256 public currentDay;

    uint256 public nextDealId = 1;
    mapping(uint256 => Deal) public deals;
    mapping(address => SupplierInfo) public suppliers;

    // ----------------------------------------------------------------- events

    event AgentChanged(address indexed agent);
    event LimitsChanged(uint256 perDealCap, uint256 dailyCap, uint256 approvalThreshold, uint64 supplierDelay);
    event EscrowPolicyChanged(uint16 maxDownBps, uint64 grace);
    event Paused(bool paused);
    event SupplierAdded(address indexed supplier, uint64 activeAt);
    event SupplierRemovedEvent(address indexed supplier);
    event DealCreated(
        uint256 indexed id,
        address indexed supplier,
        uint256 total,
        uint16 downBps,
        uint64 deadline,
        string ref,
        bool needsApproval
    );
    event DealApproved(uint256 indexed id);
    event DownPaymentReleased(uint256 indexed id, address indexed supplier, uint256 amount);
    event DeliveryConfirmed(uint256 indexed id, uint64 deliveredAt, bool onTime);
    event BalanceReleased(uint256 indexed id, address indexed supplier, uint256 amount, bool onTime);
    event DealCancelled(uint256 indexed id, address indexed supplier, uint256 refunded, bool afterDownPayment);
    event DeadlineExtended(uint256 indexed id, uint64 newDeadline);
    event DisputeRaised(uint256 indexed id, address indexed supplier);
    event DisputeResolved(uint256 indexed id, address indexed supplier, bool released, uint256 amount);
    event Withdrawn(address indexed to, uint256 amount);

    // -------------------------------------------------------------- modifiers

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyOperator() {
        if (msg.sender != owner && msg.sender != agent) revert NotOperator();
        _;
    }

    modifier notPaused() {
        if (paused) revert IsPaused();
        _;
    }

    // ------------------------------------------------------------ constructor

    /// @param _token settlement token (tokenized deposit)
    /// @param _owner the MSME owner's key; immutable
    /// @param _agent the AI agent's key; must differ from the owner
    constructor(
        address _token,
        address _owner,
        address _agent,
        uint256 _perDealCap,
        uint256 _dailyCap,
        uint256 _approvalThreshold,
        uint64 _supplierDelay
    ) {
        if (_token == address(0) || _owner == address(0) || _agent == address(0)) revert ZeroAddress();
        if (_agent == _owner) revert AgentIsOwner();
        token = IERC20(_token);
        owner = _owner;
        agent = _agent;
        perDealCap = _perDealCap;
        dailyCap = _dailyCap;
        approvalThreshold = _approvalThreshold;
        supplierDelay = _supplierDelay;
    }

    // ---------------------------------------------------------- owner: admin

    /// @notice Rotate the agent key (e.g. after a suspected compromise).
    function setAgent(address _agent) external onlyOwner {
        if (_agent == address(0)) revert ZeroAddress();
        if (_agent == owner) revert AgentIsOwner();
        agent = _agent;
        emit AgentChanged(_agent);
    }

    /// @notice Set the agent's spending envelope.
    function setLimits(uint256 _perDealCap, uint256 _dailyCap, uint256 _approvalThreshold, uint64 _supplierDelay)
        external
        onlyOwner
    {
        perDealCap = _perDealCap;
        dailyCap = _dailyCap;
        approvalThreshold = _approvalThreshold;
        supplierDelay = _supplierDelay;
        emit LimitsChanged(_perDealCap, _dailyCap, _approvalThreshold, _supplierDelay);
    }

    /// @notice Set the hard down-payment ceiling for agent deals and the cancel grace period.
    function setEscrowPolicy(uint16 _maxDownBps, uint64 _grace) external onlyOwner {
        if (_maxDownBps > BPS) revert BadBps();
        maxDownBps = _maxDownBps;
        grace = _grace;
        emit EscrowPolicyChanged(_maxDownBps, _grace);
    }

    /// @notice Stop all deal creation and payouts. Cancels (refunds into this wallet) stay open.
    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
        emit Paused(_paused);
    }

    /// @notice Whitelist a payee. It becomes payable only after `supplierDelay`.
    function addSupplier(address supplier) external onlyOwner {
        if (supplier == address(0) || supplier == address(this) || supplier == agent || supplier == owner) {
            revert BadSupplier();
        }
        SupplierInfo storage s = suppliers[supplier];
        s.listed = true;
        s.activeAt = uint64(block.timestamp) + supplierDelay;
        emit SupplierAdded(supplier, s.activeAt);
    }

    /// @notice Block new deals and down payments to a supplier. Open balances are unaffected.
    function removeSupplier(address supplier) external onlyOwner {
        suppliers[supplier].listed = false;
        emit SupplierRemovedEvent(supplier);
    }

    /// @notice Withdraw unlocked funds. Escrowed funds cannot be withdrawn.
    function withdraw(address to, uint256 amount) external onlyOwner nonReentrant {
        if (to == address(0)) revert ZeroAddress();
        if (amount > freeBalance()) revert InsufficientFreeBalance();
        token.safeTransfer(to, amount);
        emit Withdrawn(to, amount);
    }

    // --------------------------------------------------------- deal lifecycle

    /// @notice Lock the full PO amount in escrow for a whitelisted supplier.
    /// @param ref purchase order reference; untrusted free text, stored as a hash, emitted in full
    function createDeal(address supplier, uint256 total, uint16 downBps, uint64 deadline, string calldata ref)
        external
        onlyOperator
        notPaused
        returns (uint256 id)
    {
        if (!isSupplierActive(supplier)) revert SupplierNotActive();
        if (total == 0 || total > perDealCap) revert AmountOutOfRange();
        if (downBps > BPS) revert BadBps();
        if (msg.sender != owner && downBps > maxDownBps) revert DownPaymentAboveCap();
        if (deadline <= block.timestamp) revert DeadlineInPast();
        if (freeBalance() < total) revert InsufficientFreeBalance();

        id = nextDealId++;
        bool needsApproval = msg.sender != owner && total > approvalThreshold;
        deals[id] = Deal({
            supplier: supplier,
            total: total,
            downBps: downBps,
            deadline: deadline,
            deliveredAt: 0,
            status: Status.Locked,
            ownerApproved: !needsApproval,
            refHash: keccak256(bytes(ref))
        });
        locked += total;
        emit DealCreated(id, supplier, total, downBps, deadline, ref, needsApproval);
    }

    /// @notice Owner approval for an agent deal above `approvalThreshold`.
    function approveDeal(uint256 id) external onlyOwner {
        Deal storage d = deals[id];
        _expect(d, Status.Locked);
        d.ownerApproved = true;
        emit DealApproved(id);
    }

    /// @notice Pay the down payment. Counts toward the agent's daily cap.
    function releaseDownPayment(uint256 id) external onlyOperator notPaused nonReentrant {
        Deal storage d = deals[id];
        _expect(d, Status.Locked);
        if (!d.ownerApproved) revert ApprovalRequired();
        if (!suppliers[d.supplier].listed) revert SupplierRemoved();

        uint256 amount = downAmount(id);
        _checkAgentSpend(amount);
        d.status = Status.DownPaid;
        locked -= amount;
        if (amount > 0) token.safeTransfer(d.supplier, amount);
        emit DownPaymentReleased(id, d.supplier, amount);
    }

    /// @notice Owner attests the goods arrived. The only path to releasing the balance.
    /// @dev Timeliness is fixed here, so a capped or paused release never marks a supplier late.
    function confirmDelivery(uint256 id) external onlyOwner {
        Deal storage d = deals[id];
        _expect(d, Status.DownPaid);
        d.status = Status.Delivered;
        d.deliveredAt = uint64(block.timestamp);
        emit DeliveryConfirmed(id, d.deliveredAt, d.deliveredAt <= d.deadline);
    }

    /// @notice Pay the balance of an attested deal. Counts toward the agent's daily cap.
    function releaseBalance(uint256 id) external onlyOperator notPaused nonReentrant {
        Deal storage d = deals[id];
        _expect(d, Status.Delivered);

        uint256 amount = d.total - downAmount(id);
        _checkAgentSpend(amount);
        d.status = Status.Completed;
        locked -= amount;

        bool onTime = d.deliveredAt <= d.deadline;
        if (onTime) suppliers[d.supplier].completed += 1;
        else suppliers[d.supplier].late += 1;

        if (amount > 0) token.safeTransfer(d.supplier, amount);
        emit BalanceReleased(id, d.supplier, amount, onTime);
    }

    /// @notice Return unpaid escrow to the wallet's free balance.
    /// @dev Owner: any Locked deal at any time. Otherwise only after deadline + grace.
    ///      Delivered and Disputed deals cannot be cancelled.
    function cancelDeal(uint256 id) external onlyOperator nonReentrant {
        Deal storage d = deals[id];
        bool overdue = block.timestamp > uint256(d.deadline) + grace;
        uint256 remaining = 0;
        bool afterDown = false;

        if (d.status == Status.Locked) {
            if (msg.sender != owner && !overdue) revert NotOverdue();
            remaining = d.total;
        } else if (d.status == Status.DownPaid) {
            if (!overdue) revert NotOverdue();
            remaining = d.total - downAmount(id);
            afterDown = true;
            suppliers[d.supplier].late += 1;
        } else {
            revert WrongStatus(d.status);
        }

        d.status = Status.Refunded;
        locked -= remaining;
        emit DealCancelled(id, d.supplier, remaining, afterDown);
    }

    /// @notice Push a deadline later after renegotiating delivery. Never earlier.
    function extendDeadline(uint256 id, uint64 newDeadline) external onlyOwner {
        Deal storage d = deals[id];
        if (d.status != Status.Locked && d.status != Status.DownPaid) revert WrongStatus(d.status);
        if (newDeadline <= d.deadline) revert MustExtend();
        d.deadline = newDeadline;
        emit DeadlineExtended(id, newDeadline);
    }

    /// @notice Contest a down-paid deal. Freezes auto-cancel and release until resolved.
    function raiseDispute(uint256 id) external onlyOwner {
        Deal storage d = deals[id];
        _expect(d, Status.DownPaid);
        d.status = Status.Disputed;
        emit DisputeRaised(id, d.supplier);
    }

    /// @notice Settle a dispute by paying or refunding the balance.
    /// @dev Only a refund counts against the supplier, so a buyer cannot damage a
    ///      record by opening and then releasing a dispute.
    function resolveDispute(uint256 id, bool release) external onlyOwner nonReentrant {
        Deal storage d = deals[id];
        _expect(d, Status.Disputed);
        uint256 amount = d.total - downAmount(id);
        locked -= amount;
        if (release) {
            d.status = Status.Completed;
            if (amount > 0) token.safeTransfer(d.supplier, amount);
        } else {
            d.status = Status.Refunded;
            suppliers[d.supplier].late += 1;
        }
        emit DisputeResolved(id, d.supplier, release, amount);
    }

    // ------------------------------------------------------------------ views

    /// @notice Balance not committed to open deals. Returns 0 rather than reverting
    ///         if the issuer has burned below `locked`.
    function freeBalance() public view returns (uint256) {
        uint256 bal = token.balanceOf(address(this));
        return bal > locked ? bal - locked : 0;
    }

    /// @notice True if escrow holds less than open deals need (e.g. issuer clawback).
    ///         The agent's monitor halts every money-moving action while this is true.
    function isUnderfunded() external view returns (bool) {
        return token.balanceOf(address(this)) < locked;
    }

    /// @notice Down payment of a deal in token units.
    function downAmount(uint256 id) public view returns (uint256) {
        Deal storage d = deals[id];
        return (d.total * d.downBps) / BPS;
    }

    /// @notice Whitelisted and past the new-payee delay.
    function isSupplierActive(address supplier) public view returns (bool) {
        SupplierInfo storage s = suppliers[supplier];
        return s.listed && block.timestamp >= s.activeAt;
    }

    /// @notice This wallet's on-chain record of a supplier (one buyer's view).
    function supplierRecord(address supplier) external view returns (uint32 completed, uint32 late) {
        SupplierInfo storage s = suppliers[supplier];
        return (s.completed, s.late);
    }

    // --------------------------------------------------------------- internal

    function _expect(Deal storage d, Status s) internal view {
        if (d.status != s) revert WrongStatus(d.status);
    }

    /// @dev The owner is not bound by the agent's daily cap.
    function _checkAgentSpend(uint256 amount) internal {
        if (msg.sender != agent) return;
        uint256 today = block.timestamp / 1 days;
        if (today != currentDay) {
            currentDay = today;
            spentToday = 0;
        }
        if (spentToday + amount > dailyCap) revert DailyCapExceeded();
        spentToday += amount;
    }
}
