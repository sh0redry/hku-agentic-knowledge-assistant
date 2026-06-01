import os

import gradio as gr

from core.chat_interface import ChatInterface
from core.document_manager import DocumentManager
from core.rag_system import RAGSystem


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")


def create_gradio_ui():
    rag_system = RAGSystem()
    rag_system.initialize()

    doc_manager = DocumentManager(rag_system)
    chat_interface = ChatInterface(rag_system)

    def format_file_list():
        files = doc_manager.get_markdown_files()
        if not files:
            return "No documents available in the knowledge base"
        return "\n".join(files)

    def upload_handler(files, progress=gr.Progress()):
        if not files:
            return None, format_file_list()

        added, skipped = doc_manager.add_documents(
            files,
            progress_callback=lambda p, desc: progress(p, desc=desc),
        )

        gr.Info(f"Added: {added} | Skipped: {skipped}")
        return None, format_file_list()

    def clear_handler():
        doc_manager.clear_all()
        gr.Info("Removed all documents")
        return format_file_list()

    def chat_handler(msg, hist):
        for chunk in chat_interface.chat(msg, hist):
            yield chunk

    def clear_chat_handler():
        chat_interface.clear_session()

    with gr.Blocks(title="HKU Knowledge Assistant") as demo:
        with gr.Tab("Chat"):
            chatbot = gr.Chatbot(
                height=720,
                placeholder="<strong>HKU Knowledge Assistant</strong><br><em>Ask about uploaded documents or indexed HKU sources.</em>",
                show_label=False,
                avatar_images=(None, os.path.join(ASSETS_DIR, "chatbot_avatar.png")),
                layout="bubble",
            )
            chatbot.clear(clear_chat_handler)

            gr.ChatInterface(fn=chat_handler, chatbot=chatbot)

        with gr.Tab("Documents", elem_id="doc-management-tab"):
            gr.Markdown("## Documents")
            gr.Markdown("Upload PDF or Markdown files. Duplicates are skipped automatically.")

            files_input = gr.File(
                label="Drop PDF or Markdown files here",
                file_count="multiple",
                type="filepath",
                height=200,
                show_label=False,
            )

            add_btn = gr.Button("Add documents", variant="primary", size="md")

            gr.Markdown("## Knowledge base")
            file_list = gr.Textbox(
                value=format_file_list(),
                interactive=False,
                lines=7,
                max_lines=10,
                elem_id="file-list-box",
                show_label=False,
            )

            with gr.Row():
                refresh_btn = gr.Button("Refresh", size="md")
                clear_btn = gr.Button("Clear all", variant="stop", size="md")

            add_btn.click(upload_handler, [files_input], [files_input, file_list], show_progress="corner")
            refresh_btn.click(format_file_list, None, file_list)
            clear_btn.click(clear_handler, None, file_list)

    return demo
