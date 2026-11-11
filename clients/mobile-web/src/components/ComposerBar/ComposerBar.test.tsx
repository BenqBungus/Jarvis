import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/preact';
import { ComposerBar } from './ComposerBar';

describe('ComposerBar', () => {
  it('submits trimmed text and clears the input', () => {
    const onSubmit = vi.fn();
    render(<ComposerBar disabled={false} onSubmit={onSubmit} />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: '  hello jarvis  ' } });
    fireEvent.click(screen.getByTestId('composer-submit'));
    expect(onSubmit).toHaveBeenCalledWith('hello jarvis');
    expect(input.value).toBe('');
  });

  it('does not submit empty or whitespace-only text', () => {
    const onSubmit = vi.fn();
    render(<ComposerBar disabled={false} onSubmit={onSubmit} />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: '   ' } });
    fireEvent.click(screen.getByTestId('composer-submit'));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables input and submit while a task is in flight (duplicate-submit prevention)', () => {
    const onSubmit = vi.fn();
    render(<ComposerBar disabled onSubmit={onSubmit} />);
    expect(screen.getByTestId('composer-input')).toBeDisabled();
    expect(screen.getByTestId('composer-submit')).toBeDisabled();
  });

  it('submits on Enter and does not submit on Shift+Enter', () => {
    const onSubmit = vi.fn();
    render(<ComposerBar disabled={false} onSubmit={onSubmit} />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.input(input, { target: { value: 'first line' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });
    expect(onSubmit).toHaveBeenCalledWith('first line');
  });
});
