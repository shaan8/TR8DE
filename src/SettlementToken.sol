// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title Tokenized Deposit (demo settlement token)
/// @notice Each token represents one unit of fiat (e.g. CNH or USD) held
///         off-chain at the issuing bank. Only the issuer (owner) can mint or
///         burn. No trading, no taxes, no liquidity pools.
/// @dev Deploy once per currency, for example:
///      ("Tokenized Offshore RMB Deposit", "tCNH")
///      ("Tokenized USD Deposit", "tUSD")
contract SettlementToken is ERC20, Ownable {
    constructor(string memory name_, string memory symbol_)
        ERC20(name_, symbol_)
        Ownable(msg.sender)
    {}

    /// @dev 2 decimals, like cents/fen. 100 = 1.00
    function decimals() public pure override returns (uint8) {
        return 2;
    }

    /// @notice Issuer mints tokens against fiat deposited off-chain.
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /// @notice Issuer redeems (burns) tokens when fiat is paid out off-chain.
    function burn(address from, uint256 amount) external onlyOwner {
        _burn(from, amount);
    }
}
