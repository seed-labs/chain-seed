use solana_program::{
    account_info::AccountInfo,
    entrypoint,
    entrypoint::ProgramResult,
    msg,
    pubkey::Pubkey,
};

entrypoint!(process_instruction);

pub fn process_instruction(
    program_id: &Pubkey,
    accounts: &[AccountInfo],
    instruction_data: &[u8],
) -> ProgramResult {
    msg!("seedemu_solana_noop invoked");
    msg!("program_id: {}", program_id);
    msg!("account_count: {}", accounts.len());
    msg!("instruction_data_len: {}", instruction_data.len());
    Ok(())
}
