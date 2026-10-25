from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.deps import get_current_active_user
from app.models.user import User
from app.models.company import Company, CompanyStatus
from app.models.chat import ChatSession, Message
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service

router = APIRouter(prefix="/chat", tags=["chat"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/{company_id}", response_class=HTMLResponse)
async def chat_page(request: Request, company_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    company = db.query(Company).filter(Company.id == company_id, Company.user_id == current_user.id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.status != CompanyStatus.READY:
        raise HTTPException(status_code=400, detail="Bot not ready yet. Please wait for crawling to complete.")
    
    # Get or create session
    session = db.query(ChatSession).filter(ChatSession.user_id == current_user.id, ChatSession.company_id == company_id).first()
    if not session:
        session = ChatSession(user_id=current_user.id, company_id=company_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    
    messages = db.query(Message).filter(Message.session_id == session.id).order_by(Message.created_at).all()
    
    return templates.TemplateResponse("chat.html", {"request": request, "company": company, "session": session, "messages": messages})


@router.post("/{company_id}/message")
async def send_message(company_id: int, message_data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    company = db.query(Company).filter(Company.id == company_id, Company.user_id == current_user.id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.status != CompanyStatus.READY:
        raise HTTPException(status_code=400, detail="Bot not ready yet")
    
    question = message_data.get("question", "")
    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    # Get session
    session = db.query(ChatSession).filter(ChatSession.user_id == current_user.id, ChatSession.company_id == company_id).first()
    if not session:
        session = ChatSession(user_id=current_user.id, company_id=company_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    
    # Save user message
    user_msg = Message(session_id=session.id, role="user", content=question)
    db.add(user_msg)
    db.commit()
    
    # Search for relevant chunks
    relevant_chunks = rag_service.search_similar(db, company_id, question, top_k=5)
    
    # Generate answer
    llm_result = await llm_service.generate_answer(question, relevant_chunks)
    answer = llm_result.get("answer") or ""
    if not answer.strip():
        answer = "I don't know based on the available information."

    # Build citations
    citations = []
    seen_urls = set()
    for chunk in relevant_chunks:
        if chunk['url'] not in seen_urls:
            citations.append({
                "url": chunk['url'],
                "snippet": chunk['text'][:200] + "..." if len(chunk['text']) > 200 else chunk['text'],
                "chunk_id": chunk['chunk_id']
            })
            seen_urls.add(chunk['url'])
        if len(citations) >= 3:  # limit citations shown
            break

    # Save assistant message
    try:
        assistant_msg = Message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
            model=llm_result.get("model") or "",
            tokens=llm_result.get("tokens"),
            cost_usd=llm_result.get("cost_usd")
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)
    except Exception:
        db.rollback()
        assistant_msg = Message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
            model=llm_result.get("model") or "",
            tokens=llm_result.get("tokens") or 0,
            cost_usd=llm_result.get("cost_usd") or "0.0000"
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

    return {
        "answer": assistant_msg.content,
        "citations": assistant_msg.citations,
        "tokens": assistant_msg.tokens,
        "cost_usd": assistant_msg.cost_usd,
        "model": assistant_msg.model,
    }
